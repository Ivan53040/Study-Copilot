"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import courses, health, ingest, sync
from app.config.settings import get_settings
from app.database.db import init_db
from app.logging_config import get_logger
from app.sync.scheduler import SyncScheduler

logger = get_logger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Study Copilot %s", __version__)
    init_db()

    settings = get_settings()
    app.state.sync_scheduler = None
    if settings.sync.enabled and settings.sync.run_in_app:
        scheduler = SyncScheduler(settings)
        scheduler.start()
        app.state.sync_scheduler = scheduler
    try:
        yield
    finally:
        if app.state.sync_scheduler is not None:
            app.state.sync_scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Study Copilot",
        version=__version__,
        description="Local-first AI study assistant over an Obsidian vault.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(courses.router)
    app.include_router(sync.router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
