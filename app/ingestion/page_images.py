"""Render an indexed PDF page or PowerPoint slide for visual evidence."""

from __future__ import annotations

from pathlib import Path

import fitz

from app.config.settings import Settings
from app.security.paths import assert_readable


def render_page(path: str | Path, page_number: int, settings: Settings) -> bytes:
    source = assert_readable(path, settings)
    if source.suffix.lower() in {".pptx", ".ppt"}:
        # Reuse the existing PowerPoint-to-PDF preview and its content cache.
        from app.api.lectures import _preview_pdf

        preview = _preview_pdf(source, settings)
    elif source.suffix.lower() == ".pdf":
        preview = source
    else:
        raise ValueError("Only PDF and PowerPoint pages can be rendered")
    with fitz.open(preview) as pdf:
        if page_number < 1 or page_number > pdf.page_count:
            raise ValueError("Page number is out of range")
        pixmap = pdf.load_page(page_number - 1).get_pixmap(
            matrix=fitz.Matrix(1.5, 1.5), alpha=False
        )
        return pixmap.tobytes("png")
