"""Path permission enforcement.

This is the safety core of the copilot. Two guarantees:

1. **Reads** are confined to the vault's ``read_paths`` plus configured
   ``external_sources`` — never ``denied_paths`` (``.env``, ``.git``, etc.).
2. **Writes** are confined to the single ``StudyCopilot/`` output folder.

All checks resolve symlinks and ``..`` first, so path-traversal attempts
(e.g. ``StudyCopilot/../../secret``) are caught.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from app.config.settings import Settings


class PathSecurityError(PermissionError):
    """Raised when an operation targets a disallowed path."""


def _resolve(path: str | Path) -> Path:
    # resolve() collapses ``..`` and symlinks even if the file doesn't exist.
    return Path(path).expanduser().resolve()


def _is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _matches_any(path: Path, patterns: list[str], roots: list[Path]) -> bool:
    """True if ``path`` matches any glob pattern, tested relative to each root."""
    posix_full = path.as_posix()
    for root in roots:
        if not _is_relative_to(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        for pattern in patterns:
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(posix_full, pattern):
                return True
    # Also test denied-style ``**/x`` patterns against the absolute path.
    for pattern in patterns:
        if fnmatch.fnmatch(posix_full, pattern):
            return True
    return False


def is_denied(path: str | Path, settings: Settings) -> bool:
    p = _resolve(path)
    posix_full = p.as_posix()
    for pattern in settings.vault.denied_paths:
        if fnmatch.fnmatch(posix_full, pattern):
            return True
    # Defensive defaults regardless of config.
    parts = {part.lower() for part in p.parts}
    if {".git", ".ssh", ".obsidian"} & parts:
        return True
    if p.name.lower() == ".env":
        return True
    return False


def _read_roots(settings: Settings) -> list[Path]:
    return [_resolve(settings.vault.root)] + [
        _resolve(src.path) for src in settings.external_sources
    ]


def is_readable(path: str | Path, settings: Settings) -> bool:
    p = _resolve(path)
    if is_denied(p, settings):
        return False

    vault_root = _resolve(settings.vault.root)
    external_roots = [_resolve(src.path) for src in settings.external_sources]

    # External sources: any file inside a configured external dir is readable.
    if any(_is_relative_to(p, r) for r in external_roots):
        return True

    # Vault: must be under the vault root AND match a read_path glob.
    if _is_relative_to(p, vault_root):
        if not settings.vault.read_paths:
            return False
        return _matches_any(p, settings.vault.read_paths, [vault_root])

    return False


def is_writable(path: str | Path, settings: Settings) -> bool:
    p = _resolve(path)
    if is_denied(p, settings):
        return False
    output_root = _resolve(settings.output_root)
    # Writes are allowed only strictly inside StudyCopilot/.
    return _is_relative_to(p, output_root)


def assert_readable(path: str | Path, settings: Settings) -> Path:
    p = _resolve(path)
    if not is_readable(p, settings):
        raise PathSecurityError(f"Read not permitted: {p}")
    return p


def assert_writable(path: str | Path, settings: Settings) -> Path:
    p = _resolve(path)
    if not is_writable(p, settings):
        raise PathSecurityError(
            f"Write not permitted: {p}. Writes are confined to "
            f"{_resolve(settings.output_root)}"
        )
    return p


def resolve_under_vault(relative: str | Path, settings: Settings) -> Path:
    """Resolve a vault-relative path to an absolute path under the vault root."""
    return _resolve(_resolve(settings.vault.root) / relative)
