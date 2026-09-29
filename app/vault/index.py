"""In-memory vault index kept fresh by a file watcher (Obsidian-style).

Without it every tree / note / search request walks the whole vault. With it,
the app scans once at startup and then only reacts to what changed:

* a note's content changing (``modified``) re-stats just that file;
* files or folders appearing, disappearing or moving trigger one rescan in
  the watcher thread (debounced), so requests are served from memory;
* a full rescan also runs every ``_SAFETY_RESCAN_S`` seconds, in case the OS
  drops events (e.g. a burst of thousands of changes during a sync).

The index is only switched on by the running app (``enable()`` in the
lifespan). Library callers and tests that never enable it keep the direct
walk, so their behaviour is unchanged. If ``watchfiles`` is unavailable the
index still works, it just rescans on demand when older than ``_FALLBACK_TTL_S``.

Visibility rules are exactly those of ``app.vault.service.walk_vault``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config.settings import Settings
from app.logging_config import get_logger

logger = get_logger("vault.index")

_NOTE_EXTS = {".md", ".markdown", ".txt"}
_DEBOUNCE_MS = 150
_SAFETY_RESCAN_S = 120.0
_FALLBACK_TTL_S = 2.0


@dataclass
class Snapshot:
    """One consistent view of the vault's visible folders and note files."""

    generation: int
    dirs: list[str]
    # rel -> (absolute path, mtime_ns, size), in os.walk top-down order.
    files: dict[str, tuple[str, int, int]]
    _tree: dict | None = field(default=None, repr=False)
    _tree_json: bytes | None = field(default=None, repr=False)


def _key(settings: Settings) -> tuple:
    root = str(Path(settings.vault.root).expanduser().resolve())
    return (root, tuple(settings.vault.denied_paths))


class VaultIndex:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.key = _key(settings)
        self.root = self.key[0]
        self._lock = threading.RLock()  # guards scans and the snapshot
        self._snapshot: Snapshot | None = None
        self._generation = 0
        self._dirty_seq = 0  # bumped when structure (not just content) changes
        self._scanned_seq = -1
        self._touched: set[str] = set()  # notes whose content changed
        self._last_scan = 0.0
        self._watching = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="vault-index", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- reads -------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        """The current snapshot, refreshed first if anything is known to be stale."""
        with self._lock:
            stale = (
                self._snapshot is None
                or self._scanned_seq != self._dirty_seq
                or (
                    not self._watching
                    and time.monotonic() - self._last_scan > _FALLBACK_TTL_S
                )
            )
            if stale:
                self._rescan()
            elif self._touched:
                self._restat_touched()
            assert self._snapshot is not None
            return self._snapshot

    def tree(self) -> dict:
        snap = self.snapshot()
        with self._lock:
            if snap._tree is None:
                snap._tree = _build_tree(snap)
            return snap._tree

    def tree_json(self) -> bytes:
        snap = self.snapshot()
        with self._lock:
            if snap._tree_json is None:
                if snap._tree is None:
                    snap._tree = _build_tree(snap)
                snap._tree_json = json.dumps(snap._tree, ensure_ascii=False).encode("utf-8")
            return snap._tree_json

    # ---- change notifications ---------------------------------------------

    def mark_dirty(self) -> None:
        """Something structural changed (created / deleted / moved)."""
        with self._lock:
            self._dirty_seq += 1

    def touch(self, rel: str) -> None:
        """A known note's content changed; re-stat it on the next read."""
        with self._lock:
            if self._snapshot is not None and rel in self._snapshot.files:
                self._touched.add(rel)
            else:
                self._dirty_seq += 1

    # ---- internals ---------------------------------------------------------

    def _rescan(self) -> None:
        from app.vault.service import walk_vault  # local import: avoids a cycle

        seq = self._dirty_seq
        started = time.perf_counter()
        dirs: list[str] = []
        files: dict[str, tuple[str, int, int]] = {}
        for kind, rel, path, entry in walk_vault(self.settings):
            if kind == "dir":
                dirs.append(rel)
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            files[rel] = (path, st.st_mtime_ns, st.st_size)
        self._generation += 1
        self._snapshot = Snapshot(self._generation, dirs, files)
        self._touched.clear()
        self._scanned_seq = seq
        self._last_scan = time.monotonic()
        logger.debug(
            "Vault index scan: %d notes, %d folders in %.0f ms",
            len(files),
            len(dirs),
            (time.perf_counter() - started) * 1000,
        )

    def _restat_touched(self) -> None:
        assert self._snapshot is not None
        files = dict(self._snapshot.files)
        for rel in self._touched:
            item = files.get(rel)
            if item is None:
                continue
            try:
                st = os.stat(item[0])
            except OSError:
                self._dirty_seq += 1  # vanished: let a rescan settle it
                continue
            files[rel] = (item[0], st.st_mtime_ns, st.st_size)
        self._touched.clear()
        self._generation += 1
        # Structure is unchanged, so the cached tree stays valid.
        self._snapshot = Snapshot(
            self._generation,
            self._snapshot.dirs,
            files,
            self._snapshot._tree,
            self._snapshot._tree_json,
        )

    def _rel(self, path: str) -> str | None:
        """Vault-relative posix path, or None when outside / hidden."""
        try:
            rel = os.path.relpath(path, self.root)
        except ValueError:  # different drive on Windows
            return None
        rel = rel.replace(os.sep, "/")
        if rel == "." or rel.startswith("../") or rel == "..":
            return None
        if any(part.startswith(".") for part in rel.split("/")):
            return None
        return rel

    def _apply_changes(self, changes) -> None:
        from watchfiles import Change

        structural = False
        touched: list[str] = []
        with self._lock:
            snap = self._snapshot
            known_files = snap.files if snap else {}
            known_dirs = set(snap.dirs) if snap else set()
        for change, path in changes:
            rel = self._rel(path)
            if rel is None:
                continue
            suffix = Path(rel).suffix.lower()
            if change == Change.modified:
                if rel in known_files:
                    touched.append(rel)
                # Folder "modified" events just echo their children's events.
            elif change == Change.added:
                if suffix in _NOTE_EXTS or os.path.isdir(path):
                    structural = True
            else:  # deleted
                if rel in known_files or rel in known_dirs:
                    structural = True
        if structural:
            self.mark_dirty()
        for rel in touched:
            self.touch(rel)
        if structural or touched:
            try:
                self.snapshot()  # refresh now, off the request path
            except Exception:  # noqa: BLE001 - never kill the watcher
                logger.exception("Vault index refresh failed")

    def _run(self) -> None:
        try:
            self.snapshot()  # initial scan, in the background
        except Exception:  # noqa: BLE001
            logger.exception("Initial vault index scan failed")
        try:
            from watchfiles import watch
        except ImportError:
            logger.info("watchfiles not installed: vault index refreshes on demand")
            return

        def keep(_change, path: str) -> bool:
            return self._rel(path) is not None

        try:
            self._watching = True
            for changes in watch(
                self.root,
                watch_filter=keep,
                debounce=_DEBOUNCE_MS,
                step=30,
                stop_event=self._stop,
                rust_timeout=int(_SAFETY_RESCAN_S * 1000),
                yield_on_timeout=True,
                raise_interrupt=False,
                ignore_permission_denied=True,
            ):
                if self._stop.is_set():
                    break
                if changes:
                    self._apply_changes(changes)
                elif time.monotonic() - self._last_scan >= _SAFETY_RESCAN_S:
                    self.mark_dirty()
                    self.snapshot()
        except Exception:  # noqa: BLE001 - fall back to on-demand refresh
            logger.exception("Vault watcher stopped; refreshing on demand instead")
        finally:
            self._watching = False


def _build_tree(snap: Snapshot) -> dict:
    """Nested folder/file tree (same shape and order as list_tree's walk)."""
    root: dict = {"name": "", "path": "", "type": "folder", "children": {}}
    folders: dict[str, dict] = {"": root}

    def folder(rel: str) -> dict:
        node = folders.get(rel)
        if node is None:
            parent, _, name = rel.rpartition("/")
            node = {"name": name, "path": rel, "type": "folder", "children": {}}
            folder(parent)["children"][name] = node
            folders[rel] = node
        return node

    for rel in snap.dirs:
        folder(rel)
    for rel in snap.files:
        parent, _, name = rel.rpartition("/")
        folder(parent)["children"][name] = {"name": name, "path": rel, "type": "file"}

    def to_list(node: dict) -> dict:
        children = node["children"].values()
        subfolders = sorted(
            (to_list(c) for c in children if c["type"] == "folder"),
            key=lambda c: c["name"].lower(),
        )
        files = sorted(
            (c for c in children if c["type"] == "file"),
            key=lambda c: c["name"].lower(),
        )
        return {
            "name": node["name"],
            "path": node["path"],
            "type": "folder",
            "children": subfolders + files,
        }

    return to_list(root)


# ---- registry ----------------------------------------------------------------

_ENABLED = False
_REGISTRY_LOCK = threading.Lock()
_CURRENT: VaultIndex | None = None


def enable(settings: Settings) -> VaultIndex:
    """Switch the index on (called by the running app) and start watching."""
    global _ENABLED
    _ENABLED = True
    index = get(settings)
    assert index is not None
    return index


def disable() -> None:
    global _ENABLED, _CURRENT
    with _REGISTRY_LOCK:
        _ENABLED = False
        if _CURRENT is not None:
            _CURRENT.stop()
        _CURRENT = None


def get(settings: Settings) -> VaultIndex | None:
    """The live index for these settings, or None when the index is off.

    Changing the vault (Settings page) swaps in a new index automatically.
    """
    global _CURRENT
    if not _ENABLED:
        return None
    key = _key(settings)
    with _REGISTRY_LOCK:
        if _CURRENT is None or _CURRENT.key != key:
            if _CURRENT is not None:
                _CURRENT.stop()
            _CURRENT = VaultIndex(settings)
            _CURRENT.start()
        return _CURRENT


def notify_any_changed() -> None:
    """The app changed the vault's structure; rescan on the next read."""
    with _REGISTRY_LOCK:
        index = _CURRENT if _ENABLED else None
    if index is not None:
        index.mark_dirty()


def notify_changed(settings: Settings, rel: str | None = None, *, content_only: bool = False) -> None:
    """Tell the index about a change the app itself just made.

    The watcher would notice too, but a little later; this keeps
    read-after-write immediate (e.g. the tree right after a rename).
    """
    index = get(settings) if _ENABLED else None
    if index is None:
        return
    if content_only and rel is not None:
        index.touch(rel)
    else:
        index.mark_dirty()
