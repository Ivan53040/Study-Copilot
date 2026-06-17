"""Two-way sync engine tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.config.settings import Settings, SyncConfig, VaultConfig
from app.sync import twoway


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    local = tmp_path / "local"
    remote = tmp_path / "remote"
    local.mkdir()
    remote.mkdir()
    monkeypatch.setattr(twoway, "STATE_PATH", tmp_path / "state.json")
    settings = Settings(
        vault=VaultConfig(root=local, read_paths=["**"]),
        sync=SyncConfig(enabled=True, icloud_root=remote, mode="twoway"),
    )
    return local, remote, settings


def _write(p: Path, text: str, mtime: float | None = None) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def test_first_run_is_additive_union(env):
    local, remote, settings = env
    _write(local / "a.md", "local only")
    _write(remote / "b.md", "remote only")

    r = twoway.two_way_sync(settings)
    assert r.ok
    assert (remote / "a.md").exists()  # pushed up
    assert (local / "b.md").exists()  # pulled down
    assert r.deleted_local == 0 and r.deleted_remote == 0


def test_identical_files_no_conflict(env):
    local, remote, settings = env
    _write(local / "x.md", "same", mtime=1000)
    _write(remote / "x.md", "same", mtime=1000)
    r = twoway.two_way_sync(settings)
    assert r.conflicts == 0
    assert r.copied_to_local == 0 and r.copied_to_remote == 0


def test_create_local_propagates_to_remote(env):
    local, remote, settings = env
    twoway.two_way_sync(settings)  # establish empty state
    _write(local / "new.md", "hi")
    r = twoway.two_way_sync(settings)
    assert r.copied_to_remote == 1
    assert (remote / "new.md").read_text(encoding="utf-8") == "hi"


def test_delete_local_propagates_delete_to_remote(env):
    local, remote, settings = env
    _write(local / "x.md", "content")
    twoway.two_way_sync(settings)  # state now knows x.md on both sides
    assert (remote / "x.md").exists()

    (local / "x.md").unlink()
    r = twoway.two_way_sync(settings)
    assert r.deleted_remote == 1
    assert not (remote / "x.md").exists()


def test_conflict_newer_wins_and_backs_up_loser(env):
    local, remote, settings = env
    _write(local / "x.md", "v0")
    twoway.two_way_sync(settings)  # ancestor recorded

    # Modify both; make local strictly newer.
    _write(remote / "x.md", "remote edit", mtime=2000)
    _write(local / "x.md", "local edit", mtime=3000)
    r = twoway.two_way_sync(settings)

    assert r.conflicts == 1
    assert (remote / "x.md").read_text(encoding="utf-8") == "local edit"
    backups = list(remote.glob("x (sync-conflict*).md"))
    assert backups and backups[0].read_text(encoding="utf-8") == "remote edit"


def test_modify_beats_delete(env):
    local, remote, settings = env
    _write(local / "x.md", "v0")
    twoway.two_way_sync(settings)  # ancestor recorded

    (local / "x.md").unlink()  # deleted locally
    _write(remote / "x.md", "remote kept editing", mtime=5000)  # modified remotely
    r = twoway.two_way_sync(settings)

    assert (local / "x.md").read_text(encoding="utf-8") == "remote kept editing"
    assert r.copied_to_local == 1
