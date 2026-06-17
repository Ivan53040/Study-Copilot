"""Parse PDFs with PyMuPDF, preserving page numbers (1-based)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PdfPage:
    page_number: int  # 1-based
    text: str


@dataclass
class PdfDocument:
    path: Path
    pages: list[PdfPage] = field(default_factory=list)
    info: dict = field(default_factory=dict)


def parse_pdf(path: str | Path) -> PdfDocument:
    p = Path(path)
    pages: list[PdfPage] = []
    with fitz.open(str(p)) as doc:
        info = dict(doc.metadata or {})
        for index, page in enumerate(doc):
            text = page.get_text("text") or ""
            pages.append(PdfPage(page_number=index + 1, text=text.strip()))
    return PdfDocument(path=p, pages=pages, info=info)
