"""Engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.database.models import Base

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(database_url: str) -> None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        db_path = Path(database_url[len(prefix) :])
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = settings or get_settings()
        _ensure_sqlite_dir(settings.database_url)
        connect_args = (
            {"check_same_thread": False}
            if settings.database_url.startswith("sqlite")
            else {}
        )
        _engine = create_engine(
            settings.database_url, connect_args=connect_args, future=True
        )

        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _):  # pragma: no cover - trivial
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, expire_on_commit=False, future=True
        )
    return _engine


def init_db(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    Base.metadata.create_all(engine)


def get_session(settings: Settings | None = None) -> Session:
    get_engine(settings)
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Transactional scope: commits on success, rolls back on error."""
    session = get_session(settings)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Drop cached engine/sessionmaker (used by tests to switch databases)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
