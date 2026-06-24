"""Dispatch a sync run based on the configured mode."""

from __future__ import annotations

from app.config.settings import Settings, get_settings
from app.sync.icloud_sync import sync_to_icloud
from app.sync.twoway import two_way_sync


def run_sync(settings: Settings | None = None, *, dry_run: bool = False):
    """Run the appropriate sync engine. Returns an object with ``as_dict()``."""
    settings = settings or get_settings()
    mode = settings.sync.mode
    if mode == "twoway":
        return two_way_sync(settings, dry_run=dry_run)
    # "mirror" / "additive" are one-way robocopy.
    return sync_to_icloud(settings, dry_run=dry_run)
