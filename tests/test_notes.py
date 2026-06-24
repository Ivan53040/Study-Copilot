"""Phase 4 tests: templates, safe writer, and revision-note generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.generation.revision_notes import generate_revision_note
from app.ingestion.service import ingest
from app.models.chat import EchoChatAdapter
from app.obsidian.templates import (
    render_revision_note,
    revision_note_frontmatter,
)
from app.obsidian.writer import safe_filename, write_note
from app.retrieval.indexing import index_embeddings
from app.security.paths import PathSecurityError


# ---- templates ----

def test_frontmatter_marks_ai_generated():
    fm = revision_note_frontmatter(
        title="REIT6811 Week 1 Revision Notes",
        course="REIT6811",
        week=1,
        derived_from=["[[Week 1]]"],
    )
    assert fm["type"] == "revision-note"
    assert fm["source_type"] == "ai-generated"
    assert fm["reviewed_by_user"] is False
    assert fm["derived_from"] == ["[[Week 1]]"]


def test_render_note_has_banner_and_sources():
    fm = revision_note_frontmatter(
        title="T", course="REIT6811", week=1, derived_from=[]
    )
    out = render_revision_note(
        frontmatter=fm, body="## Concept\n- point [S1]", sources_section="## Sources\n- [S1] [[x]]"
    )
    assert out.startswith("---")
    assert "AI-generated revision note" in out
    assert "## Sources" in out


# ---- safe writer ----

def test_safe_filename_strips_invalid():
    assert safe_filename('a/b:c?"*.md') == "a b c .md"


def test_writer_allows_inside_studycopilot(settings, db):
    rel = "StudyCopilot/Generated Notes/test.md"
    res = write_note(rel, "hello", settings)
    assert res.written
    assert (settings.output_root / "Generated Notes" / "test.md").exists()


def test_writer_blocks_outside_studycopilot(settings, db):
    with pytest.raises(PathSecurityError):
        write_note("REIT6811 - Research Methods/hack.md", "x", settings)


# ---- generation ----

@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_generate_preview_does_not_write(indexed):
    preview = generate_revision_note(
        course="REIT6811", week=1, settings=indexed,
        adapter=EchoChatAdapter(), write=False,
    )
    assert preview.content.startswith("---")  # has frontmatter
    assert "source_type: ai-generated" in preview.content
    assert "## Sources" in preview.content
    assert preview.sources
    assert preview.written is False
    # No file created on preview.
    out_dir = indexed.output_root / "Generated Notes"
    assert not out_dir.exists() or not list(out_dir.glob("*.md"))


def test_generate_write_creates_file_in_studycopilot(indexed):
    preview = generate_revision_note(
        course="REIT6811", week=1, settings=indexed,
        adapter=EchoChatAdapter(), write=True,
    )
    assert preview.written
    written = Path(preview.target_path)
    assert written.exists()
    # Must be inside StudyCopilot/.
    assert indexed.output_root.resolve() in written.resolve().parents
    text = written.read_text(encoding="utf-8")
    assert "type: revision-note" in text and "## Sources" in text


def test_generate_no_sources_warns(settings, db):
    settings.embeddings.provider = "lmstudio"
    settings.embeddings.base_url = "http://127.0.0.1:9/v1"
    ingest(settings)
    preview = generate_revision_note(
        course="NOPE9999", settings=settings, adapter=EchoChatAdapter()
    )
    assert preview.content == ""
    assert any("No sources" in w for w in preview.warnings)
    assert preview.written is False
