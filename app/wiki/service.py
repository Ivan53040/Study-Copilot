"""Wiki build orchestration: source selection, incremental skip, job handler."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config.settings import Settings
from app.database.db import session_scope
from app.database.models import Document, WikiSource
from app.ingestion.service import ingest_single_file
from app.jobs.service import submit_job, update_progress
from app.vault.links import review_wiki_backlinks
from app.logging_config import get_logger
from app.models.chat import get_chat_adapter
from app.wiki import store
from app.wiki.pipeline import WikiPipelineError, process_source

logger = get_logger("wiki")

Progress = Callable[[int, int, str], None]


def submit_wiki_build(
    *,
    settings: Settings,
    course: str | None = None,
    scope_path: str | None = None,
    name: str | None = None,
    force: bool = False,
) -> dict:
    return submit_job(
        "wiki_build",
        {
            "course": course,
            "scope_path": scope_path,
            "name": name,
            "force": force,
        },
        settings,
    )


def submit_wiki_link_review(
    *, settings: Settings, course: str | None = None
) -> dict:
    return submit_job("wiki_link_review", {"course": course}, settings)


def run_wiki_link_review_job(payload: dict, settings: Settings, job_id: int) -> dict:
    def progress(current: int, total: int, message: str) -> None:
        update_progress(
            job_id, settings=settings, current=current, total=total, message=message
        )

    return review_wiki_backlinks(payload.get("course") or None, settings, progress)


def run_wiki_build_job(payload: dict, settings: Settings, job_id: int) -> dict:
    adapter = get_chat_adapter(
        settings, task="wiki", timeout=settings.wiki.chat_timeout_seconds
    )

    def progress(current: int, total: int, message: str) -> None:
        update_progress(
            job_id, settings=settings, current=current, total=total, message=message
        )

    return build_wiki(
        settings=settings,
        course=payload.get("course") or None,
        scope_path=payload.get("scope_path") or None,
        name=payload.get("name") or None,
        force=bool(payload.get("force")),
        adapter=adapter,
        progress=progress,
    )


def _is_under(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _source_ref(doc_path: str, settings: Settings) -> str:
    """Vault-relative path when possible (matches wikilink/frontmatter style)."""
    root = Path(settings.vault.root).expanduser().resolve()
    try:
        return Path(doc_path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return str(doc_path)


def _candidate_documents(
    settings: Settings,
    course: str | None,
    path_prefix: str | None = None,
) -> list[dict]:
    output_root = settings.output_root
    prefix = None
    if path_prefix:
        resolved = str(Path(path_prefix).expanduser().resolve()).replace("\\", "/")
        prefix = resolved.lower().rstrip("/") + "/"
    with session_scope(settings) as session:
        stmt = select(Document).order_by(Document.path)
        if course:
            stmt = stmt.where(Document.course == course)
        docs = session.scalars(stmt).all()
        wiki_rows = {
            row.document_id: row for row in session.scalars(select(WikiSource)).all()
        }

        def seen_hash(doc_id: int) -> str | None:
            row = wiki_rows.get(doc_id)
            # A failed source is retried on the next run.
            if row is None or row.status != "ok":
                return None
            return row.content_hash

        def in_scope(doc_path: str) -> bool:
            if prefix is None:
                return True
            return doc_path.replace("\\", "/").lower().startswith(prefix)

        return [
            {
                "id": doc.id,
                "path": doc.path,
                "title": doc.title,
                "course": doc.course,
                "content_hash": doc.content_hash,
                "seen_hash": seen_hash(doc.id),
            }
            for doc in docs
            # Never feed the wiki its own output (or other generated notes).
            if not _is_under(doc.path, output_root) and in_scope(doc.path)
        ]


def _source_text(doc_id: int, settings: Settings) -> str:
    with session_scope(settings) as session:
        document = session.scalar(
            select(Document)
            .where(Document.id == doc_id)
            .options(selectinload(Document.chunks))
        )
        if document is None:
            return ""
        chunks = sorted(document.chunks, key=lambda chunk: chunk.chunk_index)
        return "\n\n".join(chunk.content for chunk in chunks)


def _record_source(
    settings: Settings,
    doc: dict,
    *,
    status: str,
    summary_page: str | None = None,
    pages: list[str] | None = None,
    error: str | None = None,
) -> None:
    with session_scope(settings) as session:
        row = session.scalar(
            select(WikiSource).where(WikiSource.document_id == doc["id"])
        )
        if row is None:
            row = WikiSource(document_id=doc["id"])
            session.add(row)
        row.course = doc["course"]
        row.content_hash = doc["content_hash"]
        row.status = status
        row.error = error
        if summary_page is not None:
            row.summary_page = summary_page
        if pages is not None:
            row.pages = pages


def _index_wiki_pages(settings: Settings, rel_paths: list[str]) -> int:
    indexed = 0
    root = Path(settings.vault.root).expanduser().resolve()
    for rel in sorted(set(rel_paths)):
        try:
            report = ingest_single_file(root / rel, settings=settings)
        except Exception as exc:
            logger.warning("Could not index wiki page for search (%s): %s", rel, exc)
            continue
        if report.errors:
            logger.warning("Could not index wiki page for search (%s): %s", rel, report.errors)
            continue
        indexed += report.new + report.updated
    return indexed


def build_wiki(
    *,
    settings: Settings,
    course: str | None,
    force: bool,
    adapter,
    progress: Progress,
    scope_path: str | None = None,
    name: str | None = None,
) -> dict:
    # A wiki is identified by a label (its folder under StudyCopilot/Wiki/).
    #   - folder build: label = folder name, sources = docs under that folder;
    #   - course build: label = course code, sources = docs of that course;
    #   - "all" build:  label = None, sources = every doc, pages placed under
    #                   each document's own course.
    if scope_path:
        label: str | None = (name or Path(scope_path).name).strip() or "Notes"
        docs = _candidate_documents(settings, course=None, path_prefix=scope_path)
    else:
        label = course
        docs = _candidate_documents(settings, course=course)
    todo = [
        doc
        for doc in docs
        if force or doc["seen_hash"] is None or doc["seen_hash"] != doc["content_hash"]
    ]
    skipped = len(docs) - len(todo)
    total = len(todo) + 1
    processed = failed = 0
    pages_created: list[str] = []
    pages_updated: list[str] = []
    indexed_pages = 0
    touched_courses: set[str | None] = {
        label if label is not None else doc["course"] for doc in todo
    }

    workers = min(max(1, int(settings.wiki.max_concurrent_sources)), max(1, len(todo)))
    progress(
        0,
        total,
        f"Processing {len(todo)} sources ({skipped} unchanged, {workers} in parallel)...",
    )

    # The slow LLM calls run in parallel up to the model server's concurrency;
    # page writes, log appends, DB rows and counters are serialized via locks.
    write_lock = threading.Lock()
    state_lock = threading.Lock()
    done = 0

    def run_one(doc: dict) -> None:
        nonlocal processed, failed, done, indexed_pages
        doc_course = label if label is not None else doc["course"]
        try:
            outcome = process_source(
                title=doc["title"],
                source_ref=_source_ref(doc["path"], settings),
                source_text=_source_text(doc["id"], settings),
                course=doc_course,
                adapter=adapter,
                settings=settings,
                write_lock=write_lock,
            )
        except WikiPipelineError as exc:
            logger.warning("Wiki source failed (%s): %s", doc["title"], exc)
            with write_lock:
                _record_source(settings, doc, status="failed", error=str(exc))
                store.append_log(
                    doc_course,
                    {"source": doc["title"], "status": "failed", "error": exc},
                    settings,
                )
            with state_lock:
                failed += 1
                done += 1
                current = done
        else:
            with write_lock:
                new_indexed = _index_wiki_pages(
                    settings,
                    [outcome["summary_page"], *outcome["pages"]],
                )
                _record_source(
                    settings,
                    doc,
                    status="ok",
                    summary_page=outcome["summary_page"],
                    pages=outcome["pages"],
                )
                store.append_log(
                    doc_course,
                    {
                        "source": doc["title"],
                        "created": ",".join(f"[[{t}]]" for t in outcome["created"]) or "-",
                        "updated": ",".join(f"[[{t}]]" for t in outcome["updated"]) or "-",
                        "status": "ok",
                    },
                    settings,
                )
            with state_lock:
                processed += 1
                pages_created.extend(outcome["created"])
                pages_updated.extend(outcome["updated"])
                indexed_pages += new_indexed
                done += 1
                current = done
        progress(current, total, f"{current}/{len(todo)}: {doc['title']}")

    if todo:
        if workers == 1:
            for doc in todo:
                run_one(doc)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(run_one, todo))

    # Pages land under their wiki label's folder, so refresh the index of every
    # wiki touched this run (plus this build's label, if it has pages from
    # earlier runs).
    if label is not None:
        touched_courses.add(label)
    index_paths = [
        store.write_index(c, settings)
        for c in sorted(touched_courses, key=lambda c: c or "")
        if store.list_wiki_pages(c, settings)
    ]
    if label is None and store.list_wiki_pages(None, settings):
        index_paths.append(store.write_index(None, settings))
    progress(total, total, "Wiki build complete.")

    return {
        "course": label,
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "pages_created": pages_created,
        "pages_updated": pages_updated,
        "indexed_pages": indexed_pages,
        "index_paths": index_paths,
    }
