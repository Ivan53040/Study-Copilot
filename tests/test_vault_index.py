"""In-memory vault index: same results as a disk walk, and stays fresh."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, VaultConfig, get_settings
from app.main import app
from app.vault import index as vault_index
from app.vault.service import (
    delete_note,
    list_tree,
    note_links,
    read_note,
    rename_note,
    search_notes,
    visible_folders,
    write_note,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path) -> tuple[Settings, Path]:
    root = tmp_path / "vault"
    _write(root / "Course A" / "Week 1" / "Reliability.md", "# Reliability\nSee [[Validity]].\n")
    _write(root / "Course A" / "Week 1" / "Validity.md", "# Validity\n")
    _write(root / "Course A" / "Week 2" / "Sampling.md", "# Sampling\n")
    _write(root / ".obsidian" / "workspace.md", "hidden")
    (root / "Empty").mkdir()
    (root / "StudyCopilot").mkdir()
    settings = Settings(
        vault=VaultConfig(
            root=root,
            read_paths=["**"],
            write_paths=["StudyCopilot/**"],
            denied_paths=["**/.obsidian/**", "**/.git/**", "**/.env"],
        ),
        database_url=f"sqlite:///{(tmp_path / 'index.db').as_posix()}",
    )
    return settings, root


@pytest.fixture
def indexed(vault):
    settings, root = vault
    walked_tree = list_tree(settings)  # reference, before the index exists
    vault_index.enable(settings)
    try:
        yield settings, root, walked_tree
    finally:
        vault_index.disable()


def _files(node: dict) -> set[str]:
    if node["type"] == "file":
        return {node["path"]}
    out: set[str] = set()
    for child in node["children"]:
        out |= _files(child)
    return out


def _eventually(check, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_index_tree_matches_disk_walk(indexed):
    settings, _root, walked_tree = indexed
    assert list_tree(settings) == walked_tree
    assert "Empty" in visible_folders(settings)
    assert not any("StudyCopilot" in rel for rel in visible_folders(settings, frozenset({"StudyCopilot"})))


def test_app_writes_are_visible_immediately(indexed):
    settings, _root, _ = indexed
    write_note("Course A/Week 2/Quota.md", "# Quota\nLinks to [[Sampling]].\n", settings)
    assert "Course A/Week 2/Quota.md" in _files(list_tree(settings))
    assert any(b["path"] == "Course A/Week 2/Quota.md" for b in read_note("Course A/Week 2/Sampling.md", settings)["backlinks"])

    rename_note("Course A/Week 2/Quota.md", "Course A/Week 2/Quota sampling.md", settings)
    files = _files(list_tree(settings))
    assert "Course A/Week 2/Quota sampling.md" in files and "Course A/Week 2/Quota.md" not in files

    delete_note("Course A/Week 2/Quota sampling.md", settings)
    assert "Course A/Week 2/Quota sampling.md" not in _files(list_tree(settings))


def test_editing_a_note_updates_its_links_without_a_rescan(indexed):
    settings, _root, _ = indexed
    before = vault_index.get(settings).snapshot()
    write_note("Course A/Week 2/Sampling.md", "# Sampling\nCompare with [[Reliability]].\n", settings)
    after = vault_index.get(settings).snapshot()
    assert after.dirs is before.dirs  # structure untouched: no full rescan
    backlinks = note_links("Course A/Week 1/Reliability.md", settings)["backlinks"]
    assert {"path": "Course A/Week 2/Sampling.md", "title": "Sampling"} in backlinks


def test_watcher_picks_up_changes_made_outside_the_app(indexed):
    settings, root, _ = indexed
    index = vault_index.get(settings)
    assert _eventually(lambda: index._watching), "watcher did not start"

    _write(root / "Course A" / "Week 3" / "Ethics.md", "# Ethics\n")
    assert _eventually(lambda: "Course A/Week 3/Ethics.md" in _files(list_tree(settings)))
    assert _eventually(lambda: "Course A/Week 3" in visible_folders(settings))

    (root / "Course A" / "Week 3" / "Ethics.md").write_text("# Ethics\nSee [[Validity]].\n", encoding="utf-8")
    assert _eventually(
        lambda: any(b["path"] == "Course A/Week 3/Ethics.md" for b in note_links("Course A/Week 1/Validity.md", settings)["backlinks"])
    )

    (root / "Course A" / "Week 3" / "Ethics.md").unlink()
    assert _eventually(lambda: "Course A/Week 3/Ethics.md" not in _files(list_tree(settings)))
    assert [r["path"] for r in search_notes("ethics", settings)] == []


def test_hidden_and_denied_changes_stay_invisible(indexed):
    settings, root, _ = indexed
    _write(root / ".obsidian" / "new.md", "x")
    _write(root / ".trash" / "old.md", "x")
    time.sleep(0.6)
    files = _files(list_tree(settings))
    assert not any(rel.startswith(".") for rel in files)


def test_note_text_first_then_links_via_api(indexed):
    settings, _root, walked_tree = indexed
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        client = TestClient(app)
        text_only = client.get("/vault/note", params={"path": "Course A/Week 1/Reliability.md", "links": "false"}).json()
        assert text_only["content"].startswith("# Reliability")
        assert text_only["links"] == [] and text_only["backlinks"] == []
        assert text_only["links_loaded"] is False

        links = client.get("/vault/note-links", params={"path": "Course A/Week 1/Reliability.md"}).json()
        assert links["links"] == [{"name": "Validity", "path": "Course A/Week 1/Validity.md"}]

        full = client.get("/vault/note", params={"path": "Course A/Week 1/Validity.md"}).json()
        assert full["backlinks"] == [{"path": "Course A/Week 1/Reliability.md", "title": "Reliability"}]

        tree = client.get("/vault/tree")
        assert tree.status_code == 200 and tree.json() == walked_tree

        assert client.get("/vault/note-links", params={"path": "missing.md"}).status_code == 404
        assert client.get("/vault/note-links", params={"path": "../outside.md"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
