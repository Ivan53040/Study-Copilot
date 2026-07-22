"""Lecture-material browsing endpoints."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import fitz
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document

router = APIRouter(prefix="/lecture-materials", tags=["lecture-materials"])


def _lecture_root(settings: Settings) -> Path:
    if settings.lectures.root is not None:
        return settings.lectures.root.expanduser().resolve()
    return (Path(settings.vault.root).expanduser().resolve() / "Lecture Materials").resolve()


def _is_lecture(document: Document, settings: Settings) -> bool:
    try:
        Path(document.path).resolve().relative_to(_lecture_root(settings))
        return True
    except ValueError:
        return False


def _folder_course(doc_path: Path, lecture_root: Path) -> str | None:
    """Return the 2nd-level subfolder name under the lecture root.

    Structure: <root>/Year1Sem1/CSSE7030/file.pdf
      parts = ('Year1Sem1', 'CSSE7030', 'file.pdf')
      → returns 'CSSE7030'  (index 1)

    If the file sits only one folder deep (<root>/CSSE7030/file.pdf),
    returns that folder name (index 0) as a fallback.
    """
    try:
        rel = doc_path.resolve().relative_to(lecture_root)
        parts = rel.parts
        if len(parts) >= 3:
            return parts[1]   # 2nd-layer folder = course
        if len(parts) == 2:
            return parts[0]   # only 1 layer deep, use it directly
    except ValueError:
        pass
    return None


@router.get("")
def list_lecture_materials(settings: Settings = Depends(get_settings)) -> dict:
    root = Path(settings.vault.root).expanduser().resolve()
    lec_root = _lecture_root(settings)
    with session_scope(settings) as session:
        documents = session.scalars(
            select(Document)
            .options(selectinload(Document.chunks))
            .order_by(Document.title)
        ).all()
        items = []
        for document in documents:
            doc_path = Path(document.path)
            if not _is_lecture(document, settings):
                continue
            fc = _folder_course(doc_path, lec_root)
            try:
                rel = doc_path.resolve().relative_to(root).as_posix()
            except ValueError:
                rel = doc_path.name
            items.append({
                "id": document.id,
                "title": document.title,
                "path": document.path,
                "relative_path": rel,
                # folder_course: immediate subfolder under lecture root (most reliable)
                # course: regex-extracted metadata course code
                # The frontend prefers folder_course when set.
                "folder_course": fc,
                "course": document.course,
                "week": document.week,
                "source_type": document.source_type,
                "chunks": len(document.chunks),
                "extension": doc_path.suffix.lower(),
            })
    return {"count": len(items), "documents": items}


class ImportFolderRequest(BaseModel):
    folder_path: str


_LECTURE_EXTENSIONS = {".pdf", ".pptx", ".ppt"}
_VIEWABLE_EXTENSIONS = {".pdf", ".pptx", ".ppt"}


@router.post("/import-folder")
def import_lecture_folder(
    body: ImportFolderRequest, settings: Settings = Depends(get_settings)
) -> dict:
    return import_folder_impl(body.folder_path, settings)


def import_folder_impl(folder_path: str, settings: Settings) -> dict:
    source = Path(folder_path).expanduser().resolve()
    if not source.is_dir():
        raise HTTPException(status_code=400, detail="Not a directory")

    dest_root = _lecture_root(settings)
    dest_root.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    for src_file in source.rglob("*"):
        if src_file.is_file() and src_file.suffix.lower() in _LECTURE_EXTENSIONS:
            dest_file = dest_root / src_file.name
            # avoid overwriting with a counter suffix
            counter = 1
            while dest_file.exists():
                dest_file = dest_root / f"{src_file.stem}_{counter}{src_file.suffix}"
                counter += 1
            shutil.copy2(src_file, dest_file)
            copied.append(dest_file.as_posix())

    return {"count": len(copied), "paths": copied}


@router.get("/{document_id}")
def get_lecture_material(
    document_id: int, settings: Settings = Depends(get_settings)
) -> dict:
    with session_scope(settings) as session:
        document = session.scalar(
            select(Document)
            .where(Document.id == document_id)
            .options(selectinload(Document.chunks))
        )
        if document is None or not _is_lecture(document, settings):
            raise HTTPException(status_code=404, detail="Lecture material not found")
        chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
        return {
            "id": document.id,
            "title": document.title,
            "path": document.path,
            "course": document.course,
            "week": document.week,
            "extension": Path(document.path).suffix.lower(),
            "sections": [
                {
                    "page": chunk.page_number,
                    "heading": chunk.heading,
                    "content": chunk.content,
                }
                for chunk in chunks
            ],
        }


def _get_lecture_document(document_id: int, settings: Settings) -> tuple[int, str, Path]:
    with session_scope(settings) as session:
        document = session.get(Document, document_id)
        if document is None or not _is_lecture(document, settings):
            raise HTTPException(status_code=404, detail="Lecture material not found")
        path = Path(document.path).expanduser().resolve()
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Lecture material file is missing")
        if path.suffix.lower() not in _VIEWABLE_EXTENSIONS:
            raise HTTPException(status_code=415, detail="This file type cannot be previewed")
        return document.id, document.title, path


def _viewer_cache_dir(settings: Settings) -> Path:
    database_path = settings.database_url.removeprefix("sqlite:///")
    if database_path != settings.database_url:
        root = Path(database_path).expanduser().resolve().parent
    else:
        root = Path("data").resolve()
    cache = root / "lecture-viewer"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _powerpoint_pdf(source: Path, settings: Settings) -> Path:
    stat = source.stat()
    cache_key = hashlib.sha256(
        f"{source}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")
    ).hexdigest()[:20]
    target = _viewer_cache_dir(settings) / f"{cache_key}.pdf"
    if target.is_file() and target.stat().st_size > 0:
        return target

    script = r"""
$ErrorActionPreference = "Stop"
$source = $env:STUDY_COPILOT_PPT_SOURCE
$target = $env:STUDY_COPILOT_PPT_TARGET
$powerpoint = $null
$presentation = $null
try {
    $powerpoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerpoint.Presentations.Open($source, $true, $true, $false)
    $presentation.SaveAs($target, 32)
} finally {
    if ($null -ne $presentation) { $presentation.Close() }
    if ($null -ne $powerpoint) { $powerpoint.Quit() }
}
"""
    try:
        environment = os.environ.copy()
        environment["STUDY_COPILOT_PPT_SOURCE"] = str(source)
        environment["STUDY_COPILOT_PPT_TARGET"] = str(target)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(
            status_code=503,
            detail="PowerPoint preview could not be generated. Use Open to view the deck.",
        ) from exc
    if completed.returncode != 0 or not target.is_file():
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise HTTPException(
            status_code=503,
            detail=(
                "PowerPoint preview could not be generated. "
                f"Use Open to view the deck.{f' ({detail})' if detail else ''}"
            ),
        )
    return target


def _preview_pdf(path: Path, settings: Settings) -> Path:
    if path.suffix.lower() == ".pdf":
        return path
    return _powerpoint_pdf(path, settings)


@router.get("/{document_id}/viewer")
def get_lecture_viewer(
    document_id: int, settings: Settings = Depends(get_settings)
) -> dict:
    _, title, source = _get_lecture_document(document_id, settings)
    preview = _preview_pdf(source, settings)
    try:
        with fitz.open(preview) as pdf:
            pages = pdf.page_count
    except (fitz.FileDataError, OSError) as exc:
        raise HTTPException(status_code=422, detail="The document could not be rendered") from exc
    return {
        "id": document_id,
        "title": title,
        "extension": source.suffix.lower(),
        "pages": pages,
    }


@router.get("/{document_id}/viewer/pages/{page_number}")
def get_lecture_viewer_page(
    document_id: int,
    page_number: int,
    scale: float = Query(default=1.6, ge=0.75, le=3.0),
    settings: Settings = Depends(get_settings),
) -> Response:
    _, _, source = _get_lecture_document(document_id, settings)
    preview = _preview_pdf(source, settings)
    try:
        with fitz.open(preview) as pdf:
            if page_number < 1 or page_number > pdf.page_count:
                raise HTTPException(status_code=404, detail="Page not found")
            page = pdf.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = pixmap.tobytes("png")
    except HTTPException:
        raise
    except (fitz.FileDataError, OSError) as exc:
        raise HTTPException(status_code=422, detail="The page could not be rendered") from exc
    return Response(
        content=image,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )
