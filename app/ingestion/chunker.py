"""Semantic chunking.

Markdown is chunked by heading section; long sections are packed into
sub-chunks on paragraph boundaries. PDFs are chunked per page (preserving the
page number) and likewise split if a page is very long. Every chunk keeps the
context needed to cite it later.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ingestion.markdown_parser import MarkdownDocument
from app.ingestion.pdf_parser import PdfDocument

DEFAULT_MAX_CHARS = 1500
MIN_CHARS = 40  # drop tiny fragments (stray headings, page numbers)


@dataclass
class RawChunk:
    chunk_index: int
    content: str
    heading: str | None = None
    page_number: int | None = None


def _pack_paragraphs(text: str, max_chars: int) -> list[str]:
    """Greedily pack paragraphs into pieces no larger than max_chars."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            # Flush what we have, then hard-split the oversized paragraph.
            if current:
                pieces.append("\n\n".join(current))
                current, size = [], 0
            pieces.extend(_hard_split(para, max_chars))
            continue
        if size + len(para) + 2 > max_chars and current:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def chunk_markdown(
    doc: MarkdownDocument, max_chars: int = DEFAULT_MAX_CHARS
) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    index = 0
    for section in doc.sections:
        # Prepend the heading into the chunk content so retrieval sees it.
        body = section.content.strip()
        for piece in _pack_paragraphs(body, max_chars):
            if len(piece) < MIN_CHARS and section.heading is None:
                continue
            content = (
                f"{section.heading}\n\n{piece}" if section.heading else piece
            )
            chunks.append(
                RawChunk(
                    chunk_index=index,
                    content=content.strip(),
                    heading=section.heading,
                )
            )
            index += 1
    return chunks


def chunk_pdf(doc: PdfDocument, max_chars: int = DEFAULT_MAX_CHARS) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    index = 0
    for page in doc.pages:
        for piece in _pack_paragraphs(page.text, max_chars):
            if len(piece) < MIN_CHARS:
                continue
            chunks.append(
                RawChunk(
                    chunk_index=index,
                    content=piece.strip(),
                    page_number=page.page_number,
                )
            )
            index += 1
    return chunks
