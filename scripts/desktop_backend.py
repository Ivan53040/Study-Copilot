"""Backend entry point for the packaged desktop app (Tauri sidecar).

PyInstaller bundles this into a single executable that the Tauri shell spawns on
startup. It runs the same FastAPI app on 127.0.0.1:8000. When frozen, the working
directory may be anywhere, so we resolve the config relative to the executable's
location (config.yaml is shipped alongside it).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    # When frozen by PyInstaller, sys._MEIPASS / the exe dir hold bundled data.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def main() -> None:
    base = _base_dir()
    # Point at the shipped config unless the user overrode it.
    os.environ.setdefault("STUDY_COPILOT_CONFIG", str(base / "config.yaml"))

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
