"""Path-safe note writer. Writes are confined to StudyCopilot/ (see security)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings
from app.security.paths import assert_writable

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    """Make a string safe for a filename (Obsidian/Windows)."""
    cleaned = _INVALID.sub(" ", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "untitled"


@dataclass
class WriteResult:
    path: str
    written: bool
    bytes: int


def write_note(
    relative_or_abs_path: str | Path,
    content: str,
    settings: Settings,
    *,
    overwrite: bool = True,
) -> WriteResult:
    """Write a note. The path MUST resolve inside StudyCopilot/.

    ``relative_or_abs_path`` may be relative to the vault root (recommended) or
    absolute; either way it is validated before writing.
    """
    p = Path(relative_or_abs_path)
    if not p.is_absolute():
        p = Path(settings.vault.root) / p
    target = assert_writable(p, settings)  # raises PathSecurityError if outside

    if target.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing note: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return WriteResult(path=str(target), written=True, bytes=len(data))
