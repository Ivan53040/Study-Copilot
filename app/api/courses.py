"""Vault scope, course, and document listing endpoints."""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.vault.service import visible_folders

router = APIRouter(tags=["courses"])
_COURSE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3,4})\s?(\d{4})(?!\d)", re.I)


def _course_from_folder(folder: Path, root: Path) -> str | None:
    for part in reversed(folder.relative_to(root).parts):
        match = _COURSE_RE.search(part)
        if match:
            return f"{match.group(1)}{match.group(2)}".upper()
    return None


def _folder_document_counts(paths: list[str], root: Path) -> Counter:
    """How many indexed documents sit anywhere below each vault folder.

    One pass over the documents (counting every ancestor folder) instead of
    testing every document against every folder.
    """
    counts: Counter = Counter()
    for raw in paths:
        try:
            parts = Path(raw).relative_to(root).parts
        except ValueError:
            continue  # outside the vault (external sources, lecture folder)
        for depth in range(1, len(parts)):
            counts[os.path.normcase("/".join(parts[:depth]))] += 1
    return counts


@router.get("/scopes")
def list_scopes(settings: Settings = Depends(get_settings)) -> dict:
    """Return every visible vault folder using its exact folder name."""
    root = Path(settings.vault.root).expanduser().resolve()
    with session_scope(settings) as session:
        document_paths = list(session.scalars(select(Document.path)).all())

    if not root.is_dir():
        return {"scopes": []}

    # Visible folders only (hidden/denied pruned, StudyCopilot output skipped),
    # from the in-memory vault index when the app runs it, else one quick walk.
    folders = sorted(
        (
            (rel, root.joinpath(*rel.split("/")))
            for rel in visible_folders(settings, frozenset({"StudyCopilot"}))
        ),
        key=lambda item: item[0].lower(),
    )
    counts = _folder_document_counts(document_paths, root)
    scopes = []
    for relative, folder in folders:
        course = _course_from_folder(folder, root)
        scopes.append(
            {
                "id": f"folder:{relative}",
                "name": folder.name,
                "kind": "course" if course else "folder",
                "course": course,
                "path": str(folder),
                "documents": counts[os.path.normcase(relative)],
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
