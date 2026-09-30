"""Backend entry point for the packaged desktop app.

PyInstaller bundles this into ``study-copilot-backend.exe``, which the Tauri
shell starts (see frontend/src-tauri/src/lib.rs). It runs the same FastAPI app
as ``python -m app.main`` but keeps everything the user owns in one folder:

    <home>/config.yaml     settings (created on first run, edited in Settings)
    <home>/.env            optional cloud API keys
    <home>/data/           database, voice-note audio

``<home>`` is ``--home`` / ``STUDY_COPILOT_HOME``, else ``%APPDATA%\\Study Copilot`` on
Windows and ``~/Library/Application Support/Study Copilot`` on macOS.
The notes vault defaults to ``Documents/Study Copilot Vault`` and can be changed
in Settings.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WELCOME = """# Welcome to Study Copilot

This is your vault: a normal folder of Markdown notes. Study Copilot reads it,
answers questions from it and shows where each answer came from.

- Put your notes, lecture slides (PDF / PowerPoint) and past papers in here,
  or point Study Copilot at an existing Obsidian vault in **Settings**.
- Open **Notes** to write, **Chat** to ask questions, **Quiz** to test yourself.
- Everything the app generates goes in the `StudyCopilot/` folder. Your own notes
  are never overwritten.

Chat needs a language model. Run LM Studio (https://lmstudio.ai) with a model
loaded, or connect Claude / ChatGPT in **Settings**.
"""


def default_home() -> Path:
    # Keep in step with user_data_dir() in frontend/src-tauri/src/lib.rs.
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "Study Copilot"


def default_vault() -> Path:
    return Path.home() / "Documents" / "Study Copilot Vault"


def first_run_config(home: Path) -> str:
    """The starting config.yaml (absolute paths, so the working directory never matters)."""
    db = (home / "data" / "study_copilot.db").as_posix()
    vault = default_vault().as_posix()
    return f"""# Study Copilot settings. Most of these can be changed in the app (Settings).
vault:
  root: "{vault}"
  read_paths:
    - "**"
  write_paths:
    - "StudyCopilot/**"
  denied_paths:
    - "**/.obsidian/**"
    - "**/.git/**"
    - "**/.env"
    - "**/.ssh/**"
    - "**/.trash/**"
external_sources: []
models:
  default_provider: lmstudio
  lmstudio:
    base_url: "http://127.0.0.1:1234/v1"
    model: "local-model"
  cloud_fallback:
    enabled: false
    require_approval: true
# "hash" works offline with no embedding model. Switch to "lmstudio" (and load an
# embedding model such as nomic-embed-text) for better semantic search.
embeddings:
  provider: hash
  model: hash
retrieval:
  keyword_limit: 20
  vector_limit: 20
  final_context_limit: 8
generation:
  temperature: 0.1
  require_citations: true
sync:
  enabled: false
voice_notes:
  enabled: false
  audio_root: "{(home / "data" / "voice_notes").as_posix()}"
database_url: "sqlite:///{db}"
"""


def prepare(home: Path) -> Path:
    """Create the home folder, the first-run config and a starter vault."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    config = home / "config.yaml"
    if not config.exists():
        config.write_text(first_run_config(home), encoding="utf-8")
        vault = default_vault()
        vault.mkdir(parents=True, exist_ok=True)
        if not any(vault.iterdir()):
            (vault / "Welcome.md").write_text(WELCOME, encoding="utf-8")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Study Copilot backend")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--home", default=os.environ.get("STUDY_COPILOT_HOME"))
    args = parser.parse_args()

    home = Path(args.home) if args.home else default_home()
    config = prepare(home)
    os.environ["STUDY_COPILOT_CONFIG"] = str(config)
    os.chdir(home)  # relative paths in an older config (./data/...) resolve here

    # A GUI launch can have no console; make sure logging has somewhere to write.
    if sys.stdout is None or sys.stderr is None:
        log = open(home / "data" / "backend.log", "a", encoding="utf-8")
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log

    import uvicorn

    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
