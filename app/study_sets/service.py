"""Study set persistence and scope resolution."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import Document, StudySet, StudySetItem
from app.retrieval.types import MetadataFilter


@dataclass
class ResolvedScope:
    course: str | None
    scope_path: str | None
    document_ids: list[int]
    context_items: list[dict]
    name: str | None = None


def item_dict(item: StudySetItem) -> dict:
    return {"id": item.id, "kind": item.kind, "ref": item.ref, "mode": item.mode}


def set_dict(study_set: StudySet) -> dict:
    return {
        "id": study_set.id,
        "name": study_set.name,
        "course": study_set.course,
        "scope_path": study_set.scope_path,
        "items": [item_dict(item) for item in study_set.items],
        "created_at": study_set.created_at.isoformat(),
        "updated_at": study_set.updated_at.isoformat(),
    }


def list_study_sets(settings: Settings) -> list[dict]:
    with session_scope(settings) as session:
        rows = session.scalars(
            select(StudySet)
            .options(selectinload(StudySet.items))
            .order_by(StudySet.updated_at.desc(), StudySet.name)
        ).all()
        return [set_dict(row) for row in rows]


def get_study_set(study_set_id: int, settings: Settings) -> dict:
    with session_scope(settings) as session:
        row = session.scalar(
            select(StudySet)
            .where(StudySet.id == study_set_id)
            .options(selectinload(StudySet.items))
        )
        if row is None:
            raise KeyError(f"Study set {study_set_id} not found")
        return set_dict(row)


def save_study_set(
    *,
    settings: Settings,
    name: str,
    course: str | None = None,
    scope_path: str | None = None,
    items: list[dict] | None = None,
    study_set_id: int | None = None,
) -> dict:
    if not name.strip():
        raise ValueError("Study set name is required.")
    with session_scope(settings) as session:
        if study_set_id is None:
            row = StudySet(name=name.strip())
            session.add(row)
        else:
            row = session.scalar(
                select(StudySet)
                .where(StudySet.id == study_set_id)
                .options(selectinload(StudySet.items))
            )
            if row is None:
                raise KeyError(f"Study set {study_set_id} not found")
            for item in list(row.items):
                session.delete(item)
            row.items.clear()
        row.name = name.strip()
        row.course = course
        row.scope_path = scope_path
        session.flush()
        for raw in items or []:
            kind = str(raw.get("kind", "")).strip()
            ref = str(raw.get("ref", "")).strip()
            mode = str(raw.get("mode", "snippets")).strip() or "snippets"
            if kind not in {"document", "vault_note", "generated_note"} or not ref:
                continue
            row.items.append(
                StudySetItem(study_set_id=row.id, kind=kind, ref=ref, mode=mode)
            )
        session.flush()
        return set_dict(row)


def delete_study_set(study_set_id: int, settings: Settings) -> None:
    with session_scope(settings) as session:
        row = session.get(StudySet, study_set_id)
        if row is None:
            raise KeyError(f"Study set {study_set_id} not found")
        session.delete(row)


def resolve_scope(
    *,
    settings: Settings,
    study_set_id: int | None = None,
    course: str | None = None,
    scope_path: str | None = None,
) -> ResolvedScope:
    if study_set_id is None:
        return ResolvedScope(
            course=course,
            scope_path=scope_path,
            document_ids=[],
            context_items=[],
        )
    with session_scope(settings) as session:
        row = session.scalar(
            select(StudySet)
            .where(StudySet.id == study_set_id)
            .options(selectinload(StudySet.items))
        )
        if row is None:
            raise KeyError(f"Study set {study_set_id} not found")
        document_ids: list[int] = []
        context_items: list[dict] = []
        for item in row.items:
            if item.kind == "document":
                try:
                    doc_id = int(item.ref)
                except ValueError:
                    continue
                if session.get(Document, doc_id) is not None:
                    document_ids.append(doc_id)
                    context_items.append(
                        {"kind": "document", "ref": doc_id, "mode": item.mode}
                    )
            elif item.kind in {"vault_note", "generated_note"}:
                context_items.append(
                    {"kind": "vault_note", "ref": item.ref, "mode": item.mode}
                )
        return ResolvedScope(
            course=course if course is not None else row.course,
            scope_path=scope_path if scope_path is not None else row.scope_path,
            document_ids=document_ids,
            context_items=context_items,
            name=row.name,
        )


def metadata_filter_for_scope(
    *,
    settings: Settings,
    study_set_id: int | None = None,
    course: str | None = None,
    scope_path: str | None = None,
    week: int | None = None,
    source_type: str | None = None,
    max_trust_level: int | None = None,
) -> tuple[MetadataFilter, ResolvedScope]:
    resolved = resolve_scope(
        settings=settings,
        study_set_id=study_set_id,
        course=course,
        scope_path=scope_path,
    )
    return (
        MetadataFilter(
            course=resolved.course,
            path_prefix=resolved.scope_path,
            document_ids=resolved.document_ids or None,
            week=week,
            source_type=source_type,
            max_trust_level=max_trust_level,
        ),
        resolved,
    )
