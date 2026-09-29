"""Add searchable, page-level visual descriptions to the existing chunk index."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz
from sqlalchemy import select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.ingestion.page_images import render_page
from app.ingestion.hashing import sha256_file
from app.models.chat import ChatAdapter, ChatMessage, EchoChatAdapter, get_chat_adapter, image_message
from app.security.paths import assert_readable

_PROMPT = (
    "Describe this lecture page for search. Include visible diagram structure, "
    "labels, table headings and relationships, equations, and code tokens. "
    "Use precise terms from the page. Do not infer facts not visible. "
    "Return a concise plain-text description, no markdown."
)


@dataclass
class VisualIndexReport:
    indexed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"indexed": self.indexed, "skipped": self.skipped, "errors": self.errors}


def _page_count(path: Path, settings: Settings) -> int:
    path = assert_readable(path, settings)
    if path.suffix.lower() in {".pptx", ".ppt"}:
        from app.api.lectures import _preview_pdf

        path = _preview_pdf(path, settings)
    with fitz.open(path) as pdf:
        return pdf.page_count


def index_visual_pages(
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    *,
    document_id: int | None = None,
    limit: int | None = None,
) -> VisualIndexReport:
    """Caption source pages with a vision-capable model; reruns skip indexed pages."""
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings, task="visual_pages", timeout=180)
    if isinstance(adapter, EchoChatAdapter):
        raise ValueError("Visual page indexing requires a vision-capable model")
    report = VisualIndexReport()
    attempted = 0
    with session_scope(settings) as session:
        query = select(Document).order_by(Document.id)
        if document_id is not None:
            query = query.where(Document.id == document_id)
        documents = [
            (d.id, d.path, d.content_hash)
            for d in session.scalars(query).all()
            if Path(d.path).suffix.lower() in {".pdf", ".pptx", ".ppt"}
        ]

    for doc_id, path_text, indexed_hash in documents:
        path = Path(path_text)
        try:
            if sha256_file(assert_readable(path, settings)) != indexed_hash:
                raise ValueError("Source changed since ingestion; ingest it again first")
            count = _page_count(path, settings)
        except Exception as exc:
            report.errors.append(f"{path.name}: {exc}")
            continue
        for page_number in range(1, count + 1):
            if limit is not None and attempted >= limit:
                return report
            with session_scope(settings) as session:
                chunks = session.scalars(
                    select(Chunk).where(
                        Chunk.document_id == doc_id,
                        Chunk.page_number == page_number,
                    )
                ).all()
                if any((c.extra or {}).get("kind") == "visual_page" for c in chunks):
                    report.skipped += 1
                    continue
            attempted += 1
            try:
                png = render_page(path, page_number, settings)
                response = adapter.generate(
                    [
                        ChatMessage(role="system", content="Describe only what you can see."),
                        image_message(_PROMPT, png),
                    ],
                    temperature=0,
                    max_tokens=450,
                )
                description = response.content.strip()
                if not description:
                    raise ValueError("Visual model returned an empty description")
                with session_scope(settings) as session:
                    doc = session.get(Document, doc_id)
                    if doc is None or doc.content_hash != indexed_hash:
                        raise ValueError("Source changed during visual indexing; ingest it again")
                    next_index = max((c.chunk_index for c in doc.chunks), default=-1) + 1
                    session.add(Chunk(
                        document_id=doc_id,
                        chunk_index=next_index,
                        content=description,
                        heading=f"Visual page {page_number}",
                        page_number=page_number,
                        course=doc.course,
                        week=doc.week,
                        source_type=doc.source_type,
                        trust_level=doc.trust_level,
                        extra={"kind": "visual_page", "model": response.model},
                    ))
                report.indexed += 1
            except Exception as exc:
                report.errors.append(f"{path.name} page {page_number}: {exc}")
    return report
