"""Orchestrate the ingestion pipeline: scan -> parse -> classify -> chunk -> index."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.ingestion import metadata as meta
from app.ingestion.chunker import RawChunk, chunk_markdown, chunk_pdf
from app.ingestion.markdown_parser import parse_markdown
from app.ingestion.pdf_parser import parse_pdf
from app.ingestion.scanner import ScannedFile, diff_against_index, scan_files
from app.logging_config import get_logger
from app.security.paths import assert_readable

logger = get_logger("ingestion")


@dataclass
class IngestReport:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    chunks: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "new": self.new,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "deleted": self.deleted,
            "chunks": self.chunks,
            "errors": self.errors,
        }


def _parse_and_chunk(
    sf: ScannedFile,
) -> tuple[dict, list[RawChunk]]:
    """Return (frontmatter, chunks) for a scanned file."""
    if sf.ext in {".md", ".markdown"}:
        doc = parse_markdown(sf.path)
        return doc.frontmatter, chunk_markdown(doc)
    if sf.ext == ".pdf":
        doc = parse_pdf(sf.path)
        return {}, chunk_pdf(doc)
    if sf.ext == ".txt":
        text = Path(sf.path).read_text(encoding="utf-8", errors="replace")
        # Treat a plain-text file as one heading-less markdown body.
        from app.ingestion.markdown_parser import MarkdownDocument, _split_sections

        doc = MarkdownDocument(
            path=Path(sf.path), frontmatter={}, body=text,
            sections=_split_sections(text),
        )
        return {}, chunk_markdown(doc)
    return {}, []


def _upsert_document(
    session: Session, sf: ScannedFile, settings: Settings
) -> tuple[Document, int]:
    assert_readable(sf.path, settings)
    frontmatter, raw_chunks = _parse_and_chunk(sf)
    cls = meta.classify(
        sf.path,
        frontmatter=frontmatter,
        course_hint=sf.course_hint,
        source_type_hint=sf.source_type_hint,
    )

    existing = session.scalar(select(Document).where(Document.path == str(sf.path)))
    now = datetime.now(timezone.utc)
    if existing is None:
        doc = Document(path=str(sf.path))
        session.add(doc)
    else:
        doc = existing
        # Replace chunks on update.
        for ch in list(doc.chunks):
            session.delete(ch)
        doc.chunks.clear()

    doc.title = cls.title
    doc.course = cls.course
    doc.week = cls.week
    doc.document_type = cls.document_type
    doc.source_type = cls.source_type
    doc.trust_level = cls.trust_level
    doc.content_hash = sf.content_hash
    doc.file_modified_at = sf.file_modified_at
    doc.indexed_at = now
    session.flush()  # assign doc.id

    for rc in raw_chunks:
        doc.chunks.append(
            Chunk(
                chunk_index=rc.chunk_index,
                content=rc.content,
                heading=rc.heading,
                page_number=rc.page_number,
                course=cls.course,
                week=cls.week,
                source_type=cls.source_type,
                trust_level=cls.trust_level,
            )
        )
    return doc, len(raw_chunks)


def ingest(settings: Settings | None = None, course: str | None = None) -> IngestReport:
    """Full incremental scan + index of all approved sources."""
    settings = settings or get_settings()
    report = IngestReport()

    with session_scope(settings) as session:
        indexed = {
            d.path: d.content_hash
            for d in session.scalars(select(Document)).all()
        }
        scanned = scan_files(settings, course=course)
        diff = diff_against_index(scanned, indexed)
        report.unchanged = len(diff.unchanged)

        for sf in diff.to_ingest:
            try:
                _, n = _upsert_document(session, sf, settings)
                report.chunks += n
                if str(sf.path) in indexed:
                    report.updated += 1
                else:
                    report.new += 1
            except Exception as exc:  # keep going on per-file failures
                logger.exception("Failed to ingest %s", sf.path)
                report.errors.append(f"{sf.path}: {exc}")

        # Remove documents whose files disappeared.
        for path in diff.deleted_paths:
            doc = session.scalar(select(Document).where(Document.path == path))
            if doc is not None:
                session.delete(doc)
                report.deleted += 1

    logger.info("Ingest complete: %s", report.as_dict())
    return report


def ingest_single_file(
    file_path: str | Path, settings: Settings | None = None
) -> IngestReport:
    """Ingest one specific file (must be readable)."""
    from app.ingestion.hashing import sha256_file

    settings = settings or get_settings()
    p = assert_readable(file_path, settings)
    report = IngestReport()

    # Match external-source hints if the file lives under one.
    course_hint = source_type_hint = None
    for src in settings.external_sources:
        base = Path(src.path).expanduser().resolve()
        try:
            p.relative_to(base)
            course_hint, source_type_hint = src.course, src.source_type
            break
        except ValueError:
            continue

    from datetime import datetime as _dt

    sf = ScannedFile(
        path=p,
        ext=p.suffix.lower(),
        content_hash=sha256_file(p),
        file_modified_at=_dt.fromtimestamp(p.stat().st_mtime, tz=timezone.utc),
        course_hint=course_hint,
        source_type_hint=source_type_hint,
    )
    with session_scope(settings) as session:
        existed = session.scalar(
            select(Document.id).where(Document.path == str(p))
        )
        _, n = _upsert_document(session, sf, settings)
        report.chunks = n
        if existed:
            report.updated = 1
        else:
            report.new = 1
    return report
