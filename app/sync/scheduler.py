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
        self._startup_thread: threading.Thread | None = None
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
        # The startup sync runs separately (see run_once_in_background); this
        # loop is only for installations that also opt into interval sync.
        while not self._stop.wait(interval):
            self._run_once()

    def run_once(self) -> None:
        """Run one sync immediately and retain its result for the status API."""
        self._run_once()

    def run_once_in_background(self) -> None:
        """Kick off the startup sync without blocking app startup.

        Vault writes wait for this run via the shared lock in app.sync.gate,
        so the UI opens instantly while the vaults are still reconciled
        before the first edit.
        """
        if self._startup_thread and self._startup_thread.is_alive():
            return
        self._startup_thread = threading.Thread(
            target=self._run_once, name="icloud-sync-startup", daemon=True
        )
        self._startup_thread.start()
        logger.info("Startup sync running in the background (mode=%s)", self.settings.sync.mode)

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
        for thread in (self._thread, self._startup_thread):
            if thread:
                thread.join(timeout=5)
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
