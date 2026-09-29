"""Context for a question asked about one open note (and the notes it links to).

The chat panel next to a note answers from that note first: short notes are
given to the model whole, long ones through their most relevant indexed
passages. Notes the open note links to, and notes that link back to it, add
their best-matching passages after it.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import Document
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter, SearchHit
from app.security.paths import assert_workspace_readable

NOTE_FULL_CHARS = 6000  # notes up to this size are passed to the model whole
LINKED_NOTES = 12  # linked notes considered for extra passages
LINKED_PASSAGES = 4
NOTE_PASSAGES = 5


def _norm(path: Path | str) -> str:
    return str(path).replace("\\", "/").lower()


def _documents_by_path(paths: list[Path], settings: Settings) -> dict[str, Document]:
    if not paths:
        return {}
    wanted = {_norm(path) for path in paths}
    with session_scope(settings) as session:
        rows = session.scalars(
            select(Document).where(
                func.lower(func.replace(Document.path, "\\", "/")).in_(wanted)
            )
        ).all()
        for row in rows:
            session.expunge(row)
    return {_norm(row.path): row for row in rows}


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "\n\n[truncated]"


def _whole_note_hit(path: Path, text: str, doc: Document | None) -> SearchHit:
    return SearchHit(
        chunk_id=-1,
        document_id=doc.id if doc else 0,
        content=_clip(text, NOTE_FULL_CHARS),
        heading=None,
        page_number=None,
        course=doc.course if doc else None,
        week=doc.week if doc else None,
        source_type=doc.source_type if doc else "user-note",
        trust_level=doc.trust_level if doc else 5,
        title=doc.title if doc else path.stem,
        path=str(path),
        score=1.0,
        retrieval="note",
    )


def linked_note_paths(note_path: str, settings: Settings) -> list[str]:
    """Vault-relative paths the note links to, then notes linking back to it."""
    from app.vault.service import note_links  # local: vault imports are heavy

    links = note_links(note_path, settings)
    seen = {note_path}
    ordered: list[str] = []
    for rel in [item.get("path") for item in links.get("links", [])] + [
        item.get("path") for item in links.get("backlinks", [])
    ]:
        if rel and rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    return ordered[:LINKED_NOTES]


def note_scope_hits(
    question: str, note_path: str, settings: Settings
) -> tuple[list[SearchHit], bool]:
    """``(hits, used_vector)`` for a question about the note at ``note_path``.

    Raises ``FileNotFoundError`` for a missing note and ``PermissionError`` for
    one outside the readable vault.
    """
    root = Path(settings.vault.root).expanduser().resolve()
    path = assert_workspace_readable(root / note_path, settings)
    if not path.is_file():
        raise FileNotFoundError(f"Note not found: {note_path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    try:
        linked = linked_note_paths(note_path, settings)
    except Exception:  # links are a bonus; never fail the question over them
        linked = []
    linked_abs = []
    for rel in linked:
        try:
            linked_abs.append(assert_workspace_readable(root / rel, settings))
        except PermissionError:
            continue
    docs = _documents_by_path([path, *linked_abs], settings)
    doc = docs.get(_norm(path))

    hits: list[SearchHit] = []
    used_vector = False
    if len(text.strip()) <= NOTE_FULL_CHARS or doc is None:
        hits.append(_whole_note_hit(path, text, doc))
    else:
        own = search(
            question,
            settings=settings,
            flt=MetadataFilter(document_ids=[doc.id]),
            final_limit=NOTE_PASSAGES,
        )
        used_vector = own.used_vector
        hits.extend(own.hits or [_whole_note_hit(path, text, doc)])

    linked_ids = [
        docs[_norm(item)].id
        for item in linked_abs
        if _norm(item) in docs and docs[_norm(item)].id != (doc.id if doc else None)
    ]
    if linked_ids:
        extra = search(
            question,
            settings=settings,
            flt=MetadataFilter(document_ids=linked_ids),
            final_limit=LINKED_PASSAGES,
        )
        used_vector = used_vector or extra.used_vector
        hits.extend(extra.hits)
    return hits, used_vector
