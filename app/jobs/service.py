"""Tiny in-process background job queue for the desktop app."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Job
from app.logging_config import get_logger

logger = get_logger("jobs")

JobHandler = Callable[[dict, Settings, int], dict]
_WORKER_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None


def job_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "message": job.message,
        "payload": job.payload,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "updated_at": job.updated_at.isoformat(),
    }


def update_progress(
    job_id: int,
    *,
    settings: Settings | None = None,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> None:
    settings = settings or get_settings()
    with session_scope(settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            return
        if current is not None:
            job.progress_current = current
        if total is not None:
            job.progress_total = total
        if message is not None:
            job.message = message


def submit_job(job_type: str, payload: dict | None, settings: Settings) -> dict:
    with session_scope(settings) as session:
        job = Job(type=job_type, payload=payload or {}, status="queued")
        session.add(job)
        session.flush()
        created = job_dict(job)
    ensure_worker()
    return created


def list_jobs(settings: Settings, limit: int = 50) -> list[dict]:
    with session_scope(settings) as session:
        rows = session.scalars(
            select(Job).order_by(Job.created_at.desc()).limit(limit)
        ).all()
        return [job_dict(row) for row in rows]


def get_job(job_id: int, settings: Settings) -> dict:
    with session_scope(settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")
        return job_dict(job)


def cancel_job(job_id: int, settings: Settings) -> dict:
    with session_scope(settings) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise KeyError(f"Job {job_id} not found")
        if job.status == "queued":
            job.status = "cancelled"
            job.finished_at = datetime.now(timezone.utc)
            job.message = "Cancelled before running."
        return job_dict(job)


def ensure_worker() -> None:
    global _WORKER
    with _WORKER_LOCK:
        if _WORKER and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_worker_loop, name="study-jobs", daemon=True)
        _WORKER.start()


def _worker_loop() -> None:
    while True:
        try:
            claimed = _claim_next_job()
            if claimed is None:
                time.sleep(0.4)
                continue
            _run_job(claimed)
        except Exception:
            logger.exception("Job worker failed")
            time.sleep(1.0)


def _claim_next_job() -> dict | None:
    settings = get_settings()
    with session_scope(settings) as session:
        job = session.scalar(
            select(Job).where(Job.status == "queued").order_by(Job.created_at)
        )
        if job is None:
            return None
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        job.message = job.message or "Running..."
        session.flush()
        return {"id": job.id, "type": job.type, "payload": job.payload or {}}


def _run_job(claimed: dict) -> None:
    settings = get_settings()
    job_id = int(claimed["id"])
    try:
        handler = _handler(claimed["type"])
        result = handler(claimed["payload"], settings, job_id)
        with session_scope(settings) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.result = result or {}
            job.progress_current = job.progress_total or job.progress_current
            job.message = job.message or "Done."
            job.finished_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        with session_scope(settings) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = str(exc)
            job.message = "Failed."
            job.finished_at = datetime.now(timezone.utc)


def _handler(job_type: str) -> JobHandler:
    if job_type == "ingest_scan":
        from app.ingestion.service import ingest

        def run(payload: dict, settings: Settings, job_id: int) -> dict:
            update_progress(job_id, settings=settings, current=0, total=1, message="Scanning vault...")
            report = ingest(settings=settings, course=payload.get("course"))
            update_progress(job_id, settings=settings, current=1, total=1, message="Scan complete.")
            return report.as_dict()

        return run
    if job_type == "embedding_rebuild":
        from app.retrieval.indexing import index_embeddings

        def run(payload: dict, settings: Settings, job_id: int) -> dict:
            update_progress(job_id, settings=settings, current=0, total=1, message="Indexing embeddings...")
            report = index_embeddings(settings=settings, reindex=bool(payload.get("reindex")))
            update_progress(job_id, settings=settings, current=1, total=1, message="Embedding index complete.")
            return report.as_dict()

        return run
    if job_type == "lecture_import_scan":
        from app.api.lectures import import_folder_impl
        from app.ingestion.service import ingest

        def run(payload: dict, settings: Settings, job_id: int) -> dict:
            update_progress(job_id, settings=settings, current=0, total=2, message="Importing lecture files...")
            imported = import_folder_impl(str(payload.get("folder_path", "")), settings)
            update_progress(job_id, settings=settings, current=1, total=2, message="Indexing imported files...")
            scan = ingest(settings=settings)
            update_progress(job_id, settings=settings, current=2, total=2, message="Lecture import complete.")
            return {"imported": imported, "scan": scan.as_dict()}

        return run
    if job_type == "transformation_run":
        from app.transformations.service import run_transformation_job

        return run_transformation_job
    if job_type == "deep_ask":
        from app.deep_ask.service import run_deep_ask_job

        return run_deep_ask_job
    if job_type == "wiki_build":
        from app.wiki.service import run_wiki_build_job

        return run_wiki_build_job
    if job_type == "wiki_link_review":
        from app.wiki.service import run_wiki_link_review_job

        return run_wiki_link_review_job
    raise ValueError(f"Unsupported job type: {job_type}")
