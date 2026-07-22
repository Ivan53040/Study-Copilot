"""Generate source-grounded revision notes and (optionally) write them.

Flow: retrieve official sources -> build context -> ask the model for a note
body with [S#] citations -> validate citations -> wrap in AI-generated
frontmatter + a Sources section with backlinks -> preview, then write to
StudyCopilot/ only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.agent.context import build_context
from app.agent.prompts import NOTE_SYSTEM_PROMPT, build_note_prompt
from app.agent.validation import validate_answer
from app.config.settings import Settings, get_settings
from app.logging_config import get_logger
from app.models.chat import ChatAdapter, ChatError, ChatMessage, get_chat_adapter
from app.obsidian.links import derived_from, wikilink
from app.obsidian.templates import render_revision_note, revision_note_frontmatter
from app.obsidian.writer import WriteResult, safe_filename, write_note
from app.retrieval.citations import location
from app.retrieval.service import search
from app.retrieval.types import SearchHit
from app.study_sets.service import metadata_filter_for_scope

logger = get_logger("generation.notes")

_NOTE_CONTEXT_LIMIT = 12
_OUTPUT_SUBDIR = "StudyCopilot/Generated Notes"


@dataclass
class NotePreview:
    title: str
    target_path: str  # vault-relative
    content: str
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    written: bool = False
    model: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _scope_label(course: str | None, week: int | None, topic: str | None) -> str:
    bits = [course or "course"]
    if week is not None:
        bits.append(f"Week {week}")
    if topic:
        bits.append(topic)
    return " ".join(bits)


def _note_title(course: str | None, week: int | None, topic: str | None) -> str:
    parts = [course] if course else []
    if week is not None:
        parts.append(f"Week {week}")
    if topic:
        parts.append(topic)
    parts.append("Revision Notes")
    return " ".join(p for p in parts if p)


def _query(course: str | None, week: int | None, topic: str | None) -> str:
    if topic:
        return topic
    if week is not None:
        return f"Week {week} key concepts, definitions, and exam-relevant points"
    return "key concepts, definitions, and exam-relevant points"


def _sources_section(sources: dict[str, SearchHit]) -> str:
    lines = ["## Sources", ""]
    for sid, hit in sources.items():
        loc = location(hit)
        suffix = f" — {loc}" if loc else ""
        lines.append(f"- [{sid}] {wikilink(hit.path)}{suffix}")
    return "\n".join(lines)


def generate_revision_note(
    *,
    course: str | None = None,
    scope_path: str | None = None,
    scope_name: str | None = None,
    study_set_id: int | None = None,
    week: int | None = None,
    topic: str | None = None,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    write: bool = False,
    overwrite: bool = True,
) -> NotePreview:
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings)

    flt, resolved = metadata_filter_for_scope(
        settings=settings,
        study_set_id=study_set_id,
        course=course,
        scope_path=scope_path,
        week=week,
    )
    display_scope = resolved.course or resolved.name or scope_name
    title = _note_title(display_scope, week, topic)
    filename = safe_filename(title) + ".md"
    target_rel = f"{_OUTPUT_SUBDIR}/{filename}"

    retrieval = search(
        _query(display_scope, week, topic), settings=settings, flt=flt,
        final_limit=_NOTE_CONTEXT_LIMIT,
    )
    context = build_context(retrieval.hits)

    if context.is_empty:
        return NotePreview(
            title=title,
            target_path=target_rel,
            content="",
            warnings=["No sources found for this scope; nothing to generate."],
            model=adapter.model_name,
        )

    scope = _scope_label(display_scope, week, topic)
    messages = [
        ChatMessage(role="system", content=NOTE_SYSTEM_PROMPT),
        ChatMessage(role="user", content=build_note_prompt(scope, context.text)),
    ]

    warnings: list[str] = []
    try:
        response = adapter.generate(
            messages, temperature=settings.generation.temperature
        )
        body = response.content.strip()
        model_name = response.model
        check = validate_answer(
            body, context.sources,
            require_citations=settings.generation.require_citations,
        )
        warnings = check.warnings
    except ChatError as exc:
        logger.warning("Note model unavailable: %s", exc)
        return NotePreview(
            title=title,
            target_path=target_rel,
            content="",
            sources=[
                {**h.as_dict(include_content=False), "marker": sid}
                for sid, h in context.sources.items()
            ],
            warnings=[f"Chat model unavailable: {exc}"],
            model=adapter.model_name,
        )

    hits_in_context = list(context.sources.values())
    frontmatter = revision_note_frontmatter(
        title=title,
        course=display_scope,
        week=week,
        derived_from=derived_from(hits_in_context),
    )
    content = render_revision_note(
        frontmatter=frontmatter,
        body=body,
        sources_section=_sources_section(context.sources),
    )

    result = NotePreview(
        title=title,
        target_path=target_rel,
        content=content,
        sources=[
            {**h.as_dict(include_content=False), "marker": sid}
            for sid, h in context.sources.items()
        ],
        warnings=warnings,
        model=model_name,
    )

    if write:
        wr: WriteResult = write_note(
            target_rel, content, settings, overwrite=overwrite
        )
        result.written = True
        result.target_path = wr.path  # absolute path actually written
        logger.info("Wrote revision note: %s (%d bytes)", wr.path, wr.bytes)

    return result
