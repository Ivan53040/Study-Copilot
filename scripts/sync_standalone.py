"""CWD-independent sync entrypoint for the Windows scheduled task.

Unlike ``python -m scripts.sync`` this doesn't rely on the current working
directory: it resolves the project root and config from its own location, runs
one sync pass, and appends the result to ``data/sync.log``. Run with
``pythonw.exe`` so no console window flashes every few minutes.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("STUDY_COPILOT_CONFIG", os.path.join(ROOT, "config.yaml"))

from app.sync.service import run_sync  # noqa: E402


def main() -> None:
    log_dir = os.path.join(ROOT, "data")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "sync.log")
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        result = run_sync()
        line = f"{stamp} {json.dumps(result.as_dict())}\n"
    except Exception as exc:  # never raise out of a scheduled task
        line = f"{stamp} ERROR {exc!r}\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


if __name__ == "__main__":
    main()
