"""Freeze the backend into build/backend/study-copilot-backend/ (PyInstaller, one-folder).

Run from the project root with the project's Python:

    python -m pip install pyinstaller
    python scripts/build_backend.py

The Tauri build (frontend/src-tauri/tauri.conf.json) ships that folder inside the
installer, so end users do not need Python.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "build" / "backend"
WORK = ROOT / "build" / "pyinstaller"


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", "study-copilot-backend",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        "--paths", str(ROOT),
        # Modules imported lazily (inside functions) or by name.
        "--collect-submodules", "app",
        "--collect-submodules", "uvicorn",
        "--collect-data", "pptx",
        "--collect-data", "anthropic",
        "--hidden-import", "sqlalchemy.dialects.sqlite",
        "--hidden-import", "ruamel.yaml",
        "--hidden-import", "frontmatter",
        "--hidden-import", "markdown",
        "--hidden-import", "multipart",
        # Never bundle test tooling or the user's config / data.
        "--exclude-module", "pytest",
        "--exclude-module", "tkinter",
        str(ROOT / "scripts" / "desktop_backend.py"),
    ]
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    name = "study-copilot-backend.exe" if sys.platform == "win32" else "study-copilot-backend"
    exe = DIST / "study-copilot-backend" / name
    size = sum(f.stat().st_size for f in exe.parent.rglob("*") if f.is_file()) / 1e6
    print(f"built {exe} ({size:.0f} MB in folder)")


if __name__ == "__main__":
    main()
