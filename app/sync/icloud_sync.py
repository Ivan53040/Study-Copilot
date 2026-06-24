"""One-way sync of the local working vault to iCloud, using robocopy.

We work in a local folder (fast, no placeholder issues) and push to the
iCloud Drive folder on a timer so Obsidian on other devices stays current.

Safety:
  * The source (local vault) must exist and be non-empty. Mirroring an empty
    source with ``/PURGE`` would wipe the iCloud copy — we refuse to do that.
  * "mirror" mode uses robocopy ``/MIR`` (exact copy, deletes extras in iCloud).
    "additive" mode uses ``/E`` only (copies new/changed, never deletes).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger("sync")

# robocopy exit codes 0-7 indicate success (8+ are real errors).
_ROBOCOPY_OK_MAX = 7


class SyncError(RuntimeError):
    pass


@dataclass
class SyncResult:
    ok: bool
    mode: str
    exit_code: int
    source: str
    dest: str
    message: str

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "exit_code": self.exit_code,
            "source": self.source,
            "dest": self.dest,
            "message": self.message,
        }


def _count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


def _build_command(
    source: Path, dest: Path, mode: str, exclude_dirs: list[str]
) -> list[str]:
    cmd = ["robocopy", str(source), str(dest)]
    if mode == "mirror":
        cmd.append("/MIR")  # = /E + /PURGE
    else:  # additive
        cmd.append("/E")
    # Robustness / quiet output.
    cmd += ["/R:2", "/W:2", "/NFL", "/NDL", "/NP", "/NJH", "/NJS"]
    for d in exclude_dirs:
        cmd += ["/XD", str(source / d), d]
    return cmd


def sync_to_icloud(
    settings: Settings | None = None, *, dry_run: bool = False
) -> SyncResult:
    settings = settings or get_settings()
    sc = settings.sync

    source = Path(settings.vault.root).expanduser().resolve()
    if sc.icloud_root is None:
        raise SyncError("sync.icloud_root is not configured.")
    dest = Path(sc.icloud_root).expanduser().resolve()

    if source == dest:
        raise SyncError("Source and destination are identical; refusing to sync.")
    if not source.exists():
        raise SyncError(f"Local vault does not exist: {source}")
    if _count_files(source) == 0:
        raise SyncError(
            f"Local vault {source} is empty; refusing to mirror (would wipe iCloud)."
        )
    dest.mkdir(parents=True, exist_ok=True)

    if shutil.which("robocopy") is None:
        raise SyncError("robocopy not found (Windows-only sync).")

    cmd = _build_command(source, dest, sc.mode, sc.exclude_dirs)
    if dry_run:
        cmd.append("/L")  # list only, change nothing

    logger.info("Syncing vault -> iCloud (%s%s)", sc.mode, " dry-run" if dry_run else "")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    code = proc.returncode
    ok = code <= _ROBOCOPY_OK_MAX
    msg = (
        f"robocopy exit {code} ({'ok' if ok else 'error'})"
        + (" [dry-run]" if dry_run else "")
    )
    if not ok:
        logger.error("Sync failed: %s\n%s", msg, proc.stdout[-500:])
    else:
        logger.info("Sync done: %s", msg)
    return SyncResult(
        ok=ok,
        mode=sc.mode,
        exit_code=code,
        source=str(source),
        dest=str(dest),
        message=msg,
    )
