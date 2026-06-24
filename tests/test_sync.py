"""Sync safety + command-construction tests (no real robocopy invocation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import Settings, SyncConfig, VaultConfig
from app.sync.icloud_sync import SyncError, _build_command, sync_to_icloud


def _settings(local: Path, icloud: Path, mode: str = "mirror") -> Settings:
    return Settings(
        vault=VaultConfig(root=local, read_paths=["**"]),
        sync=SyncConfig(enabled=True, icloud_root=icloud, mode=mode),
    )


def test_mirror_uses_mir_flag():
    cmd = _build_command(Path("src"), Path("dst"), "mirror", [])
    assert "/MIR" in cmd and "/E" not in cmd


def test_additive_uses_e_not_mir():
    cmd = _build_command(Path("src"), Path("dst"), "additive", [])
    assert "/E" in cmd and "/MIR" not in cmd


def test_exclude_dirs_passed():
    cmd = _build_command(Path("src"), Path("dst"), "mirror", [".trash"])
    assert "/XD" in cmd and ".trash" in cmd


def test_refuses_empty_source(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()  # exists but empty
    icloud = tmp_path / "icloud"
    with pytest.raises(SyncError, match="empty"):
        sync_to_icloud(_settings(local, icloud))


def test_refuses_identical_source_dest(tmp_path: Path):
    same = tmp_path / "same"
    same.mkdir()
    (same / "a.md").write_text("x", encoding="utf-8")
    with pytest.raises(SyncError, match="identical"):
        sync_to_icloud(_settings(same, same))


def test_refuses_missing_icloud_root(tmp_path: Path):
    local = tmp_path / "local"
    local.mkdir()
    (local / "a.md").write_text("x", encoding="utf-8")
    s = Settings(
        vault=VaultConfig(root=local, read_paths=["**"]),
        sync=SyncConfig(enabled=True, icloud_root=None),
    )
    with pytest.raises(SyncError, match="icloud_root"):
        sync_to_icloud(s)
