"""Scan approved locations for ingestible files and detect changes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import Settings
from app.ingestion.hashing import sha256_file
from app.security.paths import is_readable

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".pptx"}


@dataclass
class ScannedFile:
    path: Path
    ext: str
    content_hash: str
    file_modified_at: datetime
    course_hint: str | None = None
    source_type_hint: str | None = None


@dataclass
class ScanResult:
    new: list[ScannedFile] = field(default_factory=list)
    changed: list[ScannedFile] = field(default_factory=list)
    unchanged: list[ScannedFile] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)

    @property
    def to_ingest(self) -> list[ScannedFile]:
        return self.new + self.changed


def _glob_base(pattern: str) -> str:
    parts: list[str] = []
    for seg in pattern.split("/"):
        if any(c in seg for c in "*?["):
            break
        parts.append(seg)
    return "/".join(parts)


def _iter_dir_files(base: Path):
    for root, dirs, files in os.walk(base):
        # Prune hidden directories (.obsidian, .git, .trash, ...).
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if name.startswith("."):
                continue
            yield Path(root) / name


def _supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def scan_files(settings: Settings, course: str | None = None) -> list[ScannedFile]:
    """Return all readable, supported files (with hashes) across approved roots."""
    seen: dict[Path, ScannedFile] = {}
    vault_root = Path(settings.vault.root).expanduser().resolve()

    # 1) Vault read_paths.
    bases: set[Path] = set()
    for pattern in settings.vault.read_paths:
        base = _glob_base(pattern)
        bases.add((vault_root / base).resolve() if base else vault_root)
    for base in bases:
        if not base.exists():
            continue
        for fpath in _iter_dir_files(base):
            rp = fpath.resolve()
            if rp in seen or not _supported(rp):
                continue
            if not is_readable(rp, settings):
                continue
            seen[rp] = ScannedFile(
                path=rp,
                ext=rp.suffix.lower(),
                content_hash=sha256_file(rp),
                file_modified_at=_mtime(rp),
            )

    # 2) Configured lectures root (if outside the vault, add it as a scan source).
    if settings.lectures.root is not None:
        lec_root = settings.lectures.root.expanduser().resolve()
        try:
            lec_root.relative_to(vault_root)
            # It's inside the vault — already covered above.
        except ValueError:
            # Outside the vault — scan it separately.
            if lec_root.exists():
                for fpath in _iter_dir_files(lec_root):
                    rp = fpath.resolve()
                    if rp in seen or not _supported(rp):
                        continue
                    seen[rp] = ScannedFile(
                        path=rp,
                        ext=rp.suffix.lower(),
                        content_hash=sha256_file(rp),
                        file_modified_at=_mtime(rp),
                        source_type_hint="lecture-source",
                    )

    # 3) External sources (carry course / source_type hints).
    for src in settings.external_sources:
        base = Path(src.path).expanduser().resolve()
        if not base.exists():
            continue
        for fpath in _iter_dir_files(base):
            rp = fpath.resolve()
            if rp in seen or not _supported(rp):
                continue
            if not is_readable(rp, settings):
                continue
            seen[rp] = ScannedFile(
                path=rp,
                ext=rp.suffix.lower(),
                content_hash=sha256_file(rp),
                file_modified_at=_mtime(rp),
                course_hint=src.course,
                source_type_hint=src.source_type,
            )

    files = list(seen.values())
    if course:
        # course hint may be unset here; filtering by course happens after
        # classification in the service. Keep this as a no-op placeholder
        # for the API's course parameter.
        pass
    return files


def diff_against_index(
    scanned: list[ScannedFile], indexed: dict[str, str]
) -> ScanResult:
    """Compare scanned files against ``{path: content_hash}`` already indexed."""
    result = ScanResult()
    scanned_paths = set()
    for sf in scanned:
        key = str(sf.path)
        scanned_paths.add(key)
        prev = indexed.get(key)
        if prev is None:
            result.new.append(sf)
        elif prev != sf.content_hash:
            result.changed.append(sf)
        else:
            result.unchanged.append(sf)
    for key in indexed:
        if key not in scanned_paths:
            result.deleted_paths.append(key)
    return result
