"""Coordinate vault writes with sync runs.

The startup sync runs in the background so the app opens instantly, but the UI
must not mutate the vault while a sync is reconciling the local and cloud
copies. Sync runs (:func:`app.sync.service.run_sync`) and vault mutations share
one reentrant lock, so a write waits for any in-flight sync and a sync waits
for any in-flight write. Reentrant because some operations (e.g. rename) call
``write_note`` internally.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.logging_config import get_logger

logger = get_logger("sync.gate")

VAULT_LOCK = threading.RLock()

_WRITE_WAIT_SECONDS = 30.0


@contextmanager
def vault_write_gate(timeout: float = _WRITE_WAIT_SECONDS) -> Iterator[None]:
    """Hold the vault for one mutation, waiting out any in-flight sync.

    Best-effort: if a sync wedges for longer than ``timeout`` the write goes
    ahead rather than freezing the UI forever (and the stall is logged).
    """
    acquired = VAULT_LOCK.acquire(timeout=timeout)
    if not acquired:
        logger.warning(
            "Vault write proceeded after waiting %.0fs for an in-flight sync",
            timeout,
        )
    try:
        yield
    finally:
        if acquired:
            VAULT_LOCK.release()
