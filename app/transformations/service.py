"""Transformation templates and job execution."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agent.context import build_context
from app.agent.manual_context import manual_hits
from app.agent.validation import validate_answer
from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import TransformationRun, TransformationTemplate
from app.jobs.service import submit_job, update_progress
from app.models.chat import ChatMessage, get_chat_adapter
from app.obsidian.links import derived_from
from app.obsidian.templates import render_frontmatter
from app.obsidian.writer import safe_filename, write_note
from app.retrieval.service import search
from app.retrieval.types import SearchHit
from app.study_sets.service import metadata_filter_for_scope, resolve_scope

_OUTPUT_DIR = "StudyCopilot/Generated Notes/Transformations"


def template_dict(template: TransformationTemplate) -> dict:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "prompt": template.prompt,
        "apply_default": template.apply_default,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def run_dict(run: TransformationRun) -> dict:
    return {
        "id": run.id,
        "template_id": run.template_id,
        "target_kind": run.target_kind,
        "target_ref": run.target_ref,
        "study_set_id": run.study_set_id,
        "job_id": run.job_id,
        "output_path": run.output_path,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def list_templates(settings: Settings) -> list[dict]:
    with session_scope(settings) as session:
        rows = session.scalars(
            select(TransformationTemplate).order_by(TransformationTemplate.name)
        ).all()
        return [template_dict(row) for row in rows]


def save_template(
    *,
    settings: Settings,
    name: str,
    description: str,
    prompt: str,
    apply_default: bool = False,
    template_id: int | None = None,
) -> dict:
    if not name.strip() or not prompt.strip():
        raise ValueError("Template name and prompt are required.")
    with session_scope(settings) as session:
        if template_id is None:
            template = TransformationTemplate(name=name.strip(), prompt=prompt.strip())
            session.add(template)
        else:
            template = session.get(TransformationTemplate, template_id)
            if template is None:
                raise KeyError(f"Template {template_id} not found")
        template.name = name.strip()
        template.description = description.strip()
        template.prompt = prompt.strip()
        template.apply_default = bool(apply_default)
        session.flush()
        return template_dict(template)


def delete_template(template_id: int, settings: Settings) -> None:
    with session_scope(settings) as session:
        template = session.get(TransformationTemplate, template_id)
        if template is None:
            raise KeyError(f"Template {template_id} not found")
        session.delete(template)


def submit_transformation(
    *,
    settings: Settings,
    template_id: int,
    target_kind: str,
    target_ref: str | None = None,
    study_set_id: int | None = None,
) -> dict:
    if target_kind not in {"document", "vault_note", "study_set"}:
        raise ValueError("Unsupported transformation target.")
    with session_scope(settings) as session:
        template = session.get(TransformationTemplate, template_id)
        if template is None:
            raise KeyError(f"Template {template_id} not found")
        run = TransformationRun(
            template_id=template_id,
            target_kind=target_kind,
            target_ref=target_ref,
            study_set_id=study_set_id,
            status="queued",
        )
        session.add(run)
        session.flush()
        run_id = run.id
    job = submit_job(
        "transformation_run",
        {"run_id": run_id},
        settings,
    )
    with session_scope(settings) as session:
        run = session.get(TransformationRun, run_id)
        assert run is not None
        run.job_id = job["id"]
        session.flush()
        return {"run": run_dict(run), "job": job}


def run_transformation_job(payload: dict, settings: Settings, job_id: int) -> dict:
    run_id = int(payload["run_id"])
    with session_scope(settings) as session:
        run = session.scalar(
            select(TransformationRun)
            .where(TransformationRun.id == run_id)
            .options(selectinload(TransformationRun.template))
        )
        if run is None or run.template is None:
            raise KeyError(f"Transformation run {run_id} not found")
        run.status = "running"
        template = run.template
        target_kind = run.target_kind
        target_ref = run.target_ref
        study_set_id = run.study_set_id

    update_progress(job_id, settings=settings, current=0, total=3, message="Building transformation context...")
    hits = _target_hits(target_kind, target_ref, study_set_id, settings)
    context = build_context(hits, max_chars=max(4000, settings.retrieval.final_context_limit * 1200))
    if context.is_empty:
        raise ValueError("No source content found for this transformation.")

    update_progress(job_id, settings=settings, current=1, total=3, message="Running transformation...")
    adapter = get_chat_adapter(settings, task="transformations")
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You transform study materials into faithful Markdown notes. "
                "Use only the provided SOURCES and cite claims with [S#]."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"SOURCES:\n{context.text}\n\n"
                f"TASK TEMPLATE: {template.name}\n{template.prompt}\n\n"
                "Return the Markdown body now, with [S#] citations."
            ),
        ),
    ]
    response = adapter.generate(messages, temperature=settings.generation.temperature)
    body = response.content.strip()
    check = validate_answer(
        body,
        context.sources,
        require_citations=settings.generation.require_citations,
    )

    title = f"{template.name} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H%M')}"
    frontmatter = {
        "title": title,
        "type": "transformation-note",
        "source_type": "ai-generated",
        "reviewed_by_user": False,
        "generated_at": datetime.now(timezone.utc).date().isoformat(),
        "transformation": template.name,
        "derived_from": derived_from(list(context.sources.values())),
    }
    source_lines = ["## Sources", ""]
    for sid, hit in context.sources.items():
        source_lines.append(f"- [{sid}] [[{hit.title}]]")
    warnings = "\n".join(f"> [!warning] {warning}" for warning in check.warnings)
    content = "\n".join(
        part
        for part in [
            render_frontmatter(frontmatter),
            "",
            "> [!warning] AI-generated transformation note - review before relying on it.",
            warnings,
            "",
            body,
            "",
            "\n".join(source_lines),
            "",
        ]
        if part is not None
    )
    rel = f"{_OUTPUT_DIR}/{safe_filename(title)}.md"
    update_progress(job_id, settings=settings, current=2, total=3, message="Writing transformation note...")
    written = write_note(rel, content, settings, overwrite=True)
    with session_scope(settings) as session:
        run = session.get(TransformationRun, run_id)
        assert run is not None
        run.status = "succeeded"
        run.output_path = written.path
        run.finished_at = datetime.now(timezone.utc)
    update_progress(job_id, settings=settings, current=3, total=3, message="Transformation complete.")
    return {
        "run_id": run_id,
        "output_path": written.path,
        "title": title,
        "warnings": check.warnings,
        "model": response.model,
    }


def _target_hits(
    target_kind: str,
    target_ref: str | None,
    study_set_id: int | None,
    settings: Settings,
) -> list[SearchHit]:
    if target_kind == "document":
        if target_ref is None:
            return []
        return manual_hits(
            [{"kind": "document", "ref": target_ref, "mode": "full"}],
            settings=settings,
        )
    if target_kind == "vault_note":
        if not target_ref:
            return []
        return manual_hits(
            [{"kind": "vault_note", "ref": target_ref, "mode": "full"}],
            settings=settings,
        )
    if target_kind == "study_set" and study_set_id is not None:
        resolved = resolve_scope(settings=settings, study_set_id=study_set_id)
        hits = manual_hits(resolved.context_items, settings=settings)
        if hits:
            return hits
        if resolved.course or resolved.scope_path:
            flt, _ = metadata_filter_for_scope(
                settings=settings,
                study_set_id=study_set_id,
            )
            return search(
                "key concepts and important study material",
                settings=settings,
                flt=flt,
                final_limit=12,
            ).hits
    return []
