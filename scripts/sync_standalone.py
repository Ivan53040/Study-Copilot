"""CWD-independent sync entrypoint.

Resolves the project root and config from its own location, runs one sync pass,
and appends the result to ``data/sync.log``. Run with ``pythonw.exe`` so no
console window flashes.

Modes:
  (default)    Sync now, but skip if Study Copilot is open (manual safety).
  --on-close   Spawned by the app as it exits: wait for the app to fully close
               (its backend port frees), then sync once.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STUDY_COPILOT_CONFIG", os.path.join(ROOT, "config.yaml"))

from app.sync.service import desktop_app_running, run_sync  # noqa: E402

# How long to wait for the app to finish closing before syncing (--on-close).
_CLOSE_WAIT_SECONDS = 30


def _sync_line() -> str:
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        result = run_sync()
        return f"{stamp} {json.dumps(result.as_dict())}\n"
    except Exception as exc:  # never raise out of a background launch
        return f"{stamp} ERROR {exc!r}\n"


def _skip_line(reason: str) -> str:
    stamp = datetime.now().isoformat(timespec="seconds")
    return f"{stamp} skipped: {reason}\n"


def main() -> None:
    log_dir = os.path.join(ROOT, "data")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "sync.log")

    if "--on-close" in sys.argv:
        # Launched by the app on exit: give the backend a moment to shut down so
        # the app and sync never write the vault at once, then sync.
        deadline = time.monotonic() + _CLOSE_WAIT_SECONDS
        while desktop_app_running() and time.monotonic() < deadline:
            time.sleep(1.0)
        line = (
            _skip_line("app still running after close")
            if desktop_app_running()
            else _sync_line()
        )
    elif desktop_app_running():
        line = _skip_line("Study Copilot is open")
    else:
        line = _sync_line()

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()
