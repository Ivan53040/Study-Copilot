"""Manifest-based two-way sync between the local vault and iCloud.

robocopy can only mirror one direction. True bidirectional sync must tell apart
"deleted on side A" from "created on side B" — which needs a record of the last
synced state (a manifest / common ancestor). This module:

  1. Loads the ancestor snapshot from the previous successful sync.
  2. Scans both sides now.
  3. Classifies each path on each side as created / modified / deleted / same.
  4. Reconciles:
       * change on one side only  -> propagate (copy or delete) to the other
       * both modified            -> newer mtime wins; the loser is backed up
                                      as a ``(sync-conflict ...)`` copy first
       * modify vs delete         -> modification wins (resurrect the file)
       * both deleted             -> drop it
  5. Saves the new ancestor snapshot.

First run (no manifest) is a safe additive union merge: everything present is
treated as "created", so files are copied across but **nothing is deleted**.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger("sync.twoway")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = PROJECT_ROOT / "data" / "sync_state.json"

# mtime comparison tolerance (filesystems differ in resolution).
MTIME_TOLERANCE = 2.0

# Never sync these (high-churn / machine-specific / junk).
DEFAULT_EXCLUDE_GLOBS = [
    ".obsidian/workspace.json",
    ".obsidian/workspace-mobile.json",
    ".obsidian/workspace*.json",
    "**/.DS_Store",
    "**/desktop.ini",
    "**/*.icloud",
]
DEFAULT_EXCLUDE_DIRS = {".trash", ".git"}


@dataclass
class FileInfo:
    size: int
    mtime: float


@dataclass
class TwoWayResult:
    ok: bool = True
    mode: str = "twoway"
    dry_run: bool = False
    copied_to_remote: int = 0
    copied_to_local: int = 0
    deleted_remote: int = 0
    deleted_local: int = 0
    conflicts: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "copied_to_remote": self.copied_to_remote,
            "copied_to_local": self.copied_to_local,
            "deleted_remote": self.deleted_remote,
            "deleted_local": self.deleted_local,
            "conflicts": self.conflicts,
            "errors": self.errors,
        }


def _same(a: FileInfo | None, b: FileInfo | None) -> bool:
    if a is None or b is None:
        return False
    return a.size == b.size and abs(a.mtime - b.mtime) <= MTIME_TOLERANCE


def _excluded(rel: str, exclude_dirs: set[str], exclude_globs: list[str]) -> bool:
    parts = set(Path(rel).parts)
    if parts & exclude_dirs:
        return True
    return any(fnmatch.fnmatch(rel, g) for g in exclude_globs)


def _scan(root: Path, exclude_dirs: set[str], exclude_globs: list[str]) -> dict[str, FileInfo]:
    out: dict[str, FileInfo] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if _excluded(rel, exclude_dirs, exclude_globs):
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            out[rel] = FileInfo(size=st.st_size, mtime=st.st_mtime)
    return out


def _load_state() -> dict[str, FileInfo]:
    if not STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read sync state; treating as first run.")
        return {}
    return {k: FileInfo(size=v[0], mtime=v[1]) for k, v in raw.items()}


def _save_state(state: dict[str, FileInfo]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serial = {k: [v.size, v.mtime] for k, v in state.items()}
    STATE_PATH.write_text(json.dumps(serial), encoding="utf-8")


def _status(now: FileInfo | None, ancestor: FileInfo | None) -> str:
    if now is not None and ancestor is None:
        return "created"
    if now is not None and ancestor is not None:
        return "same" if _same(now, ancestor) else "modified"
    if now is None and ancestor is not None:
        return "deleted"
    return "absent"


def _copy(src_root: Path, dst_root: Path, rel: str) -> None:
    src = src_root / rel
    dst = dst_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)  # preserves mtime so the next scan sees them equal


def _delete(root: Path, rel: str) -> None:
    target = root / rel
    if target.exists():
        target.unlink()


def _backup_name(root: Path, rel: str) -> Path:
    p = root / rel
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    return p.with_name(f"{p.stem} (sync-conflict {stamp}){p.suffix}")


def two_way_sync(
    settings: Settings | None = None, *, dry_run: bool = False
) -> TwoWayResult:
    settings = settings or get_settings()
    sc = settings.sync
    result = TwoWayResult(dry_run=dry_run)

    local = Path(settings.vault.root).expanduser().resolve()
    if sc.icloud_root is None:
        result.ok = False
        result.errors.append("sync.icloud_root is not configured.")
        return result
    remote = Path(sc.icloud_root).expanduser().resolve()
    if local == remote:
        result.ok = False
        result.errors.append("Source and destination are identical.")
        return result
    if not local.exists():
        result.ok = False
        result.errors.append(f"Local vault does not exist: {local}")
        return result
    remote.mkdir(parents=True, exist_ok=True)

    exclude_dirs = DEFAULT_EXCLUDE_DIRS | set(sc.exclude_dirs)
    exclude_globs = DEFAULT_EXCLUDE_GLOBS

    ancestor = _load_state()
    lstate = _scan(local, exclude_dirs, exclude_globs)
    rstate = _scan(remote, exclude_dirs, exclude_globs)

    new_state: dict[str, FileInfo] = {}
    all_paths = set(ancestor) | set(lstate) | set(rstate)

    for rel in sorted(all_paths):
        li, ri, ai = lstate.get(rel), rstate.get(rel), ancestor.get(rel)
        sl, sr = _status(li, ai), _status(ri, ai)
        changed_l = sl in {"created", "modified", "deleted"}
        changed_r = sr in {"created", "modified", "deleted"}

        try:
            # No real change anywhere.
            if not changed_l and not changed_r:
                if li is not None:
                    new_state[rel] = li
                continue

            # If both sides already agree on content, just record it.
            if li is not None and ri is not None and _same(li, ri):
                new_state[rel] = li
                continue

            # Change on local only -> push to remote.
            if changed_l and not changed_r:
                if sl in {"created", "modified"}:
                    if not dry_run:
                        _copy(local, remote, rel)
                    result.copied_to_remote += 1
                    new_state[rel] = li  # type: ignore[assignment]
                else:  # deleted locally -> delete remote
                    if not dry_run:
                        _delete(remote, rel)
                    result.deleted_remote += 1
                continue

            # Change on remote only -> pull to local.
            if changed_r and not changed_l:
                if sr in {"created", "modified"}:
                    if not dry_run:
                        _copy(remote, local, rel)
                    result.copied_to_local += 1
                    new_state[rel] = ri  # type: ignore[assignment]
                else:  # deleted remotely -> delete local
                    if not dry_run:
                        _delete(local, rel)
                    result.deleted_local += 1
                continue

            # Changed on BOTH sides.
            if sl == "deleted" and sr == "deleted":
                continue  # gone everywhere
            # Modify-beats-delete: resurrect the surviving edit.
            if sl == "deleted" and ri is not None:
                if not dry_run:
                    _copy(remote, local, rel)
                result.copied_to_local += 1
                new_state[rel] = ri
                continue
            if sr == "deleted" and li is not None:
                if not dry_run:
                    _copy(local, remote, rel)
                result.copied_to_remote += 1
                new_state[rel] = li
                continue

            # Both present and differing -> conflict, newer mtime wins.
            assert li is not None and ri is not None
            result.conflicts += 1
            if li.mtime >= ri.mtime:
                winner_root, loser_root, winner_info = local, remote, li
            else:
                winner_root, loser_root, winner_info = remote, local, ri
            if not dry_run:
                # Back up the loser before overwriting, then copy winner over.
                loser_backup = _backup_name(loser_root, rel)
                shutil.copy2(loser_root / rel, loser_backup)
                _copy(winner_root, loser_root, rel)
            if winner_root == local:
                result.copied_to_remote += 1
            else:
                result.copied_to_local += 1
            new_state[rel] = winner_info
        except OSError as exc:
            logger.exception("Sync error on %s", rel)
            result.errors.append(f"{rel}: {exc}")
            # Preserve whatever we last knew to avoid spurious deletes next run.
            if ai is not None:
                new_state[rel] = ai

    if not dry_run:
        _save_state(new_state)

    result.ok = not result.errors
    logger.info("Two-way sync: %s", result.as_dict())
    return result
