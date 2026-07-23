"""Semantic chunking.

Markdown is chunked by heading section; long sections are packed into
sub-chunks on paragraph boundaries. PDFs are chunked per page (preserving the
page number) and likewise split if a page is very long. Every chunk keeps the
context needed to cite it later.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.config.settings import Settings
from app.ingestion.markdown_parser import MarkdownDocument
from app.ingestion.pdf_parser import PdfDocument

DEFAULT_MAX_CHARS = 1500
MIN_CHARS = 40  # drop tiny fragments (stray headings, page numbers)
DEFAULT_MIN_TOKENS = 4
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


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


def _token_count(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def _tokens_to_chars(tokens: int) -> int:
    # Conservative conversion for mixed prose/Markdown without adding a tokenizer.
    return max(240, tokens * 4)


def _limits(settings: Settings | None, max_chars: int | None) -> tuple[int, int]:
    if max_chars is not None:
        return max_chars, DEFAULT_MIN_TOKENS
    if settings is None:
        return DEFAULT_MAX_CHARS, DEFAULT_MIN_TOKENS
    return (
        _tokens_to_chars(settings.ingestion.chunk_tokens),
        max(1, settings.ingestion.min_chunk_tokens),
    )


def chunk_markdown(
    doc: MarkdownDocument,
    max_chars: int | None = None,
    settings: Settings | None = None,
) -> list[RawChunk]:
    max_chars, min_tokens = _limits(settings, max_chars)
    chunks: list[RawChunk] = []
    index = 0
    for section in doc.sections:
        # Prepend the heading into the chunk content so retrieval sees it.
        body = section.content.strip()
        for piece in _pack_paragraphs(body, max_chars):
            if _token_count(piece) < min_tokens:
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


def chunk_pdf(
    doc: PdfDocument,
    max_chars: int | None = None,
    settings: Settings | None = None,
) -> list[RawChunk]:
    max_chars, min_tokens = _limits(settings, max_chars)
    chunks: list[RawChunk] = []
    index = 0
    for page in doc.pages:
        for piece in _pack_paragraphs(page.text, max_chars):
            if _token_count(piece) < min_tokens:
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
