"""Chunker tests."""

from __future__ import annotations

from app.ingestion.chunker import _pack_paragraphs, chunk_markdown
from app.ingestion.markdown_parser import MarkdownDocument, _split_sections


def _md(body: str) -> MarkdownDocument:
    return MarkdownDocument(
        path=None, frontmatter={}, body=body, sections=_split_sections(body)
    )


def test_sections_split_on_headings():
    body = "# A\n\ntext a\n\n## B\n\ntext b\n"
    doc = _md(body)
    headings = [s.heading for s in doc.sections]
    assert "A" in headings and "B" in headings


def test_heading_included_in_chunk_content():
    doc = _md("# Reliability\n\nReliability is consistency of measurement here.\n")
    chunks = chunk_markdown(doc)
    assert chunks
    assert chunks[0].heading == "Reliability"
    assert "Reliability" in chunks[0].content


def test_headings_inside_code_fence_ignored():
    body = "# Real\n\n```\n# not a heading\n```\n\nbody text goes on here.\n"
    doc = _md(body)
    headings = [s.heading for s in doc.sections]
    assert "not a heading" not in headings


def test_pack_paragraphs_respects_max():
    text = "\n\n".join(["para " * 50 for _ in range(10)])
    pieces = _pack_paragraphs(text, max_chars=400)
    assert len(pieces) > 1
    assert all(len(p) <= 400 + 10 for p in pieces)


def test_chunk_indices_are_sequential():
    body = "# A\n\n" + ("word " * 400) + "\n\n# B\n\n" + ("word " * 400)
    chunks = chunk_markdown(_md(body), max_chars=500)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
