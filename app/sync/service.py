"""Dispatch a sync run based on the configured mode."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.sync.gate import VAULT_LOCK
from app.sync.icloud_sync import sync_to_icloud
from app.sync.twoway import two_way_sync


# Ports Study Copilot backends use: 8765 (default / older desktop builds),
# 8766 (dev script), 8767 (one-click launcher), 8768 (desktop app).
APP_PORTS = (8765, 8766, 8767, 8768)
# The desktop app records its backend port here (it may pick another port
# when 8768 is taken) and removes the file when it closes.
_PORT_FILE = Path(__file__).resolve().parents[2] / "data" / "desktop-port.txt"


def _registered_ports() -> tuple[int, ...]:
    try:
        port = int(_PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return ()
    return (port,) if 0 < port < 65536 else ()


def _study_copilot_on(port: int, host: str, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return False  # nothing listening
    # Something is listening. Another program may own this port, so only
    # count it when it answers like Study Copilot's /health. Anything that
    # does not answer clearly is treated as the app (never sync by mistake).
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/health", timeout=max(timeout, 1.0)
        ) as response:
            data = json.loads(response.read(65536).decode("utf-8", "replace"))
    except urllib.error.HTTPError:
        return False  # a web server without Study Copilot's /health
    except Exception:  # noqa: BLE001 - timeouts, resets, non-HTTP listeners
        return True
    return isinstance(data, dict) and "vault_root" in data


def desktop_app_running(
    port: int | None = None, host: str = "127.0.0.1", timeout: float = 0.4
) -> bool:
    """True if a Study Copilot backend appears to be running.

    Used by the background sync task to defer syncing until the app is
    closed (so the app and sync never write the vault at the same time).
    Checks ``port``, or every port in ``APP_PORTS``. A port held by some
    other program (one that answers HTTP but is not Study Copilot) does not
    count, so it can no longer block syncing forever.
    """
    ports = (
        (port,)
        if port is not None
        else tuple(dict.fromkeys(APP_PORTS + _registered_ports()))
    )
    return any(_study_copilot_on(p, host, timeout) for p in ports)


def run_sync(settings: Settings | None = None, *, dry_run: bool = False):
    """Run the appropriate sync engine. Returns an object with ``as_dict()``.

    Serialised against vault writes (and other sync runs) through the shared
    vault lock in :mod:`app.sync.gate`, so a sync never rewrites files under an
    in-progress edit.
    """
    settings = settings or get_settings()
    with VAULT_LOCK:
        mode = settings.sync.mode
        if mode == "twoway":
            return two_way_sync(settings, dry_run=dry_run)
        # "mirror" / "additive" are one-way robocopy.
        return sync_to_icloud(settings, dry_run=dry_run)
