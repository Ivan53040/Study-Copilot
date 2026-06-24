"""Vault scope, course, and document listing endpoints."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.security.paths import is_denied

router = APIRouter(tags=["courses"])
_COURSE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3,4})\s?(\d{4})(?!\d)", re.I)


def _course_from_folder(folder: Path, root: Path) -> str | None:
    for part in reversed(folder.relative_to(root).parts):
        match = _COURSE_RE.search(part)
        if match:
            return f"{match.group(1)}{match.group(2)}".upper()
    return None


def _document_count(documents: list[Document], folder: Path) -> int:
    return sum(
        1 for document in documents if Path(document.path).is_relative_to(folder)
    )


@router.get("/scopes")
def list_scopes(settings: Settings = Depends(get_settings)) -> dict:
    """Return every visible vault folder using its exact folder name."""
    root = Path(settings.vault.root).expanduser().resolve()
    with session_scope(settings) as session:
        documents = list(session.scalars(select(Document)).all())

    if not root.is_dir():
        return {"scopes": []}

    folders = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_dir()
            and not path.name.startswith(".")
            and not is_denied(path, settings)
            and "StudyCopilot" not in path.relative_to(root).parts
        ),
        key=lambda path: str(path.relative_to(root)).lower(),
    )
    scopes = []
    for folder in folders:
        course = _course_from_folder(folder, root)
        relative = folder.relative_to(root).as_posix()
        scopes.append(
            {
                "id": f"folder:{relative}",
                "name": folder.name,
                "kind": "course" if course else "folder",
                "course": course,
                "path": str(folder),
                "documents": _document_count(documents, folder),
            }
        )
    return {"scopes": scopes}


@router.get("/courses")
def list_courses(settings: Settings = Depends(get_settings)) -> dict:
    with session_scope(settings) as session:
        rows = session.execute(
            select(
                Document.course,
                func.count(func.distinct(Document.id)),
                func.count(Chunk.id),
            )
            .outerjoin(Chunk, Chunk.document_id == Document.id)
            .group_by(Document.course)
        ).all()
    return {
        "courses": [
            {
                "course": course or "(unclassified)",
                "label": course or "(unclassified)",
                "documents": documents,
                "chunks": chunks,
            }
            for course, documents, chunks in rows
        ]
    }


@router.get("/courses/{course}/documents")
def list_documents(
    course: str, settings: Settings = Depends(get_settings)
) -> dict:
    normalised = course.replace(" ", "").upper()
    with session_scope(settings) as session:
        docs = session.scalars(
            select(Document)
            .where(func.upper(Document.course) == normalised)
            .order_by(Document.week, Document.title)
        ).all()
        result = [_document_dict(document) for document in docs]
    return {"course": normalised, "count": len(result), "documents": result}


@router.get("/scope-documents")
def list_scope_documents(
    path: str = Query(...), settings: Settings = Depends(get_settings)
) -> dict:
    prefix = str(Path(path).resolve()).replace("\\", "/").lower().rstrip("/") + "/"
    with session_scope(settings) as session:
        docs = session.scalars(select(Document).order_by(Document.title)).all()
        selected = [
            document
            for document in docs
            if document.path.replace("\\", "/").lower().startswith(prefix)
        ]
        result = [_document_dict(document) for document in selected]
    return {"path": path, "count": len(result), "documents": result}


def _document_dict(document: Document) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "week": document.week,
        "document_type": document.document_type,
        "source_type": document.source_type,
        "trust_level": document.trust_level,
        "chunks": len(document.chunks),
        "path": document.path,
    }
