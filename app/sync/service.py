"""Dispatch a sync run based on the configured mode."""

from __future__ import annotations

import socket

from app.config.settings import Settings, get_settings
from app.sync.icloud_sync import sync_to_icloud
from app.sync.twoway import two_way_sync


def desktop_app_running(
    port: int = 8000, host: str = "127.0.0.1", timeout: float = 0.4
) -> bool:
    """True if the Study Copilot desktop app appears to be open.

    The packaged app spawns its backend on 127.0.0.1:8000 and kills it on exit,
    so a reachable port is a reliable "app is open" signal. Used by the
    background sync task to defer syncing until the app is closed (avoids the
    app and sync writing the vault at the same time).
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run_sync(settings: Settings | None = None, *, dry_run: bool = False):
    """Run the appropriate sync engine. Returns an object with ``as_dict()``."""
    settings = settings or get_settings()
    mode = settings.sync.mode
    if mode == "twoway":
        return two_way_sync(settings, dry_run=dry_run)
    # "mirror" / "additive" are one-way robocopy.
    return sync_to_icloud(settings, dry_run=dry_run)
