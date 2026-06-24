"""Background scheduler that mirrors the vault to iCloud on an interval."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from app.config.settings import Settings
from app.logging_config import get_logger
from app.sync.service import run_sync

logger = get_logger("sync.scheduler")


class SyncScheduler:
    """Runs ``sync_to_icloud`` every ``interval_minutes`` in a daemon thread."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_result = None
        self.last_run_at: datetime | None = None
        self.last_error: str | None = None

    def _run_once(self) -> None:
        try:
            self.last_result = run_sync(self.settings)
            self.last_error = None
        except Exception as exc:  # never let a sync failure kill the thread
            self.last_error = str(exc)
            logger.exception("Scheduled sync failed")
        finally:
            self.last_run_at = datetime.now(timezone.utc)

    def _loop(self) -> None:
        interval = max(1, self.settings.sync.interval_minutes) * 60
        # First sync shortly after startup, then every interval.
        if not self._stop.wait(10):
            self._run_once()
        while not self._stop.wait(interval):
            self._run_once()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="icloud-sync", daemon=True
        )
        self._thread.start()
        logger.info(
            "Sync scheduler started (every %s min, mode=%s)",
            self.settings.sync.interval_minutes,
            self.settings.sync.mode,
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Sync scheduler stopped")

    def status(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_minutes": self.settings.sync.interval_minutes,
            "mode": self.settings.sync.mode,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_result": self.last_result.as_dict() if self.last_result else None,
            "last_error": self.last_error,
        }
