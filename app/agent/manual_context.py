"""Build SearchHit-like context from explicitly selected sources."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import Document
from app.retrieval.types import SearchHit
from app.security.paths import assert_workspace_readable


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n\n[truncated]"


def manual_hits(
    items: list[dict],
    *,
    settings: Settings,
    max_chars_per_item: int = 4000,
) -> list[SearchHit]:
    hits: list[SearchHit] = []
    next_id = -1
    for item in items:
        if item.get("mode") == "exclude":
            continue
        kind = item.get("kind")
        ref = item.get("ref")
        if kind == "document":
            try:
                doc_id = int(ref)
            except (TypeError, ValueError):
                continue
            hit = _document_hit(doc_id, item.get("mode", "snippets"), settings, next_id, max_chars_per_item)
        elif kind in {"vault_note", "generated_note"}:
            hit = _vault_note_hit(str(ref), settings, next_id, max_chars_per_item)
        else:
            hit = None
        if hit is not None:
            hits.append(hit)
            next_id -= 1
    return hits


def _document_hit(
    doc_id: int,
    mode: str,
    settings: Settings,
    chunk_id: int,
    max_chars: int,
) -> SearchHit | None:
    with session_scope(settings) as session:
        document = session.scalar(
            select(Document)
            .where(Document.id == doc_id)
            .options(selectinload(Document.chunks))
        )
        if document is None:
            return None
        chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
        selected = chunks if mode == "full" else chunks[:3]
        content = "\n\n".join(chunk.content for chunk in selected)
        return SearchHit(
            chunk_id=chunk_id,
            document_id=document.id,
            content=_clip(content, max_chars),
            heading=None,
            page_number=None,
            course=document.course,
            week=document.week,
            source_type=document.source_type,
            trust_level=document.trust_level,
            title=document.title,
            path=document.path,
            score=1.0,
            retrieval="manual",
        )


def _vault_note_hit(
    relpath: str,
    settings: Settings,
    chunk_id: int,
    max_chars: int,
) -> SearchHit | None:
    root = Path(settings.vault.root).expanduser().resolve()
    path = assert_workspace_readable(root / relpath, settings)
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    return SearchHit(
        chunk_id=chunk_id,
        document_id=0,
        content=_clip(content, max_chars),
        heading=None,
        page_number=None,
        course=None,
        week=None,
        source_type="user-note",
        trust_level=5,
        title=path.stem,
        path=str(path),
        score=1.0,
        retrieval="manual",
    )
