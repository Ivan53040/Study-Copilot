"""Application lifecycle integration for vault sync."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

from app import main as main_module
from app.config.settings import Settings, SyncConfig, VaultConfig
from app.sync import gate as sync_gate
from app.sync import service as sync_service


def _settings(tmp_path) -> Settings:
    return Settings(
        vault=VaultConfig(root=tmp_path / "vault"),
        sync=SyncConfig(
            enabled=True,
            icloud_root=tmp_path / "icloud",
            mode="twoway",
            run_in_app=False,
        ),
    )


def test_startup_syncs_in_background_without_starting_interval_loop(
    tmp_path, monkeypatch
):
    settings = _settings(tmp_path)
    events: list[str] = []
    started = threading.Event()
    release = threading.Event()

    class FakeScheduler:
        def __init__(self, received_settings):
            assert received_settings is settings

        def run_once(self):
            events.append("run_once")
            started.set()
            release.wait(timeout=5)

        def run_once_in_background(self):
            threading.Thread(target=self.run_once, daemon=True).start()

        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "SyncScheduler", FakeScheduler)
    test_app = SimpleNamespace(state=SimpleNamespace())

    async def exercise_lifespan():
        async with main_module.lifespan(test_app):
            assert test_app.state.sync_scheduler is not None
            # Startup must not wait for the sync to finish...
            assert started.wait(timeout=5)
            assert events == ["run_once"]
            release.set()

    asyncio.run(exercise_lifespan())

    # ...and run_in_app=False must not start the interval loop.
    assert events == ["run_once", "stop"]


def test_vault_writes_wait_for_in_flight_sync(tmp_path, monkeypatch):
    """A vault write blocks while run_sync holds the vault lock, then proceeds."""
    settings = _settings(tmp_path)
    syncing = threading.Event()
    release = threading.Event()

    def fake_two_way_sync(_settings, *, dry_run=False):
        syncing.set()
        release.wait(timeout=5)
        return SimpleNamespace(as_dict=lambda: {"mode": "twoway", "dry_run": dry_run})

    monkeypatch.setattr(sync_service, "two_way_sync", fake_two_way_sync)

    sync_thread = threading.Thread(
        target=sync_service.run_sync, args=(settings,), daemon=True
    )
    sync_thread.start()
    assert syncing.wait(timeout=5)  # sync now holds the vault lock

    write_done = threading.Event()

    def writer():
        with sync_gate.vault_write_gate(timeout=5):
            write_done.set()

    write_thread = threading.Thread(target=writer, daemon=True)
    write_thread.start()

    # The write must wait while the sync is still running...
    assert not write_done.wait(timeout=0.2)
    release.set()
    # ...and proceed once the sync releases the lock.
    assert write_done.wait(timeout=5)
    sync_thread.join(timeout=5)
    write_thread.join(timeout=5)
