"""Engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import Settings, get_settings
from app.database.models import Base

# FTS5 full-text index over chunks, kept in sync via triggers. Uses an
# external-content table so the text lives once in `chunks`.
_FTS_SQL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        content, heading,
        content='chunks', content_rowid='id',
        tokenize='porter unicode61'
    );
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, content, heading)
        VALUES (new.id, new.content, coalesce(new.heading, ''));
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, heading)
        VALUES ('delete', old.id, old.content, coalesce(old.heading, ''));
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, content, heading)
        VALUES ('delete', old.id, old.content, coalesce(old.heading, ''));
        INSERT INTO chunks_fts(rowid, content, heading)
        VALUES (new.id, new.content, coalesce(new.heading, ''));
    END;
    """,
]


def _ensure_fts(engine: Engine) -> None:
    """Create the FTS5 table/triggers and (re)sync from chunks."""
    if not engine.url.get_backend_name().startswith("sqlite"):
        return
    with engine.begin() as conn:
        for stmt in _FTS_SQL:
            conn.execute(text(stmt))
        # Rebuild from the content table so pre-existing chunks get indexed.
        conn.execute(text("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')"))

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
    _ensure_fts(engine)


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
