"""End-to-end ingestion tests against the temp vault."""

from __future__ import annotations

from sqlalchemy import select

from app.database.db import session_scope
from app.database.models import Chunk, Document
from app.ingestion.service import ingest


def test_ingest_indexes_course_files(settings, db):
    report = ingest(settings)
    assert report.new == 2  # two markdown files in the temp course folder
    assert report.chunks > 0
    assert report.errors == []

    with session_scope(settings) as session:
        docs = session.scalars(select(Document)).all()
        paths = [d.path for d in docs]
        assert all("REIT6811" in p for p in paths)
        # The .env and .obsidian files must NOT be indexed.
        assert not any(".env" in p or ".obsidian" in p for p in paths)


def test_reingest_is_incremental(settings, db):
    first = ingest(settings)
    second = ingest(settings)
    assert second.new == 0
    assert second.updated == 0
    assert second.unchanged == first.new


def test_change_detection_reindexes(settings, db):
    ingest(settings)
    note = (
        settings.vault.root
        / "REIT6811 - Research Methods"
        / "REIT6811_Mock_Exam_1.md"
    )
    note.write_text("# Mock Exam 1\n\nUpdated content entirely.\n", encoding="utf-8")
    report = ingest(settings)
    assert report.updated == 1


def test_deleted_file_is_removed(settings, db):
    ingest(settings)
    note = (
        settings.vault.root
        / "REIT6811 - Research Methods"
        / "REIT6811_Mock_Exam_1.md"
    )
    note.unlink()
    report = ingest(settings)
    assert report.deleted == 1
    with session_scope(settings) as session:
        remaining = session.scalars(select(Document)).all()
        assert all("Mock_Exam_1" not in d.path for d in remaining)


def test_chunks_carry_citation_metadata(settings, db):
    ingest(settings)
    with session_scope(settings) as session:
        chunk = session.scalars(select(Chunk)).first()
        assert chunk is not None
        assert chunk.course == "REIT6811"
        assert chunk.trust_level >= 1
