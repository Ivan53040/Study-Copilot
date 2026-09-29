"""The fast vault walker must expose exactly what the old os.walk + is_denied did."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings, VaultConfig, get_settings
from app.database import db as db_module
from app.database.db import session_scope
from app.database.models import Document
from app.main import app
from app.security.paths import is_denied
from app.vault.service import NOTE_EXTS, _iter_notes, list_tree, walk_vault


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def messy_vault(tmp_path: Path) -> tuple[Settings, Path]:
    root = tmp_path / "vault"
    outside = tmp_path / "outside"
    _write(root / "Notes" / "a.md")
    _write(root / "Notes" / "sub" / "b.md")
    _write(root / "Notes" / "sub" / "c.txt")
    _write(root / "Notes" / "image.png")
    _write(root / "Notes" / ".draft.md")
    _write(root / ".hidden" / "x.md")
    _write(root / ".obsidian" / "y.md")
    _write(root / "Notes" / "private" / "p.md")
    _write(root / "COMP3506 Algorithms" / "Week 1" / "w1.md")
    _write(root / "StudyCopilot" / "Generated Notes" / "gen.md")
    (root / "Empty folder").mkdir()
    _write(outside / "secret.md")
    _write(outside / ".ssh" / "key.md")
    try:
        os.symlink(outside / "secret.md", root / "Notes" / "linked-ok.md")
        os.symlink(outside / ".ssh" / "key.md", root / "Notes" / "linked-denied.md")
        os.symlink(outside, root / "Notes" / "linked-folder", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available here")
    settings = Settings(
        vault=VaultConfig(
            root=root,
            read_paths=["**"],
            write_paths=["StudyCopilot/**"],
            denied_paths=["**/.obsidian/**", "**/.git/**", "**/.env", "**/private/**"],
        ),
        database_url=f"sqlite:///{(tmp_path / 'walk.db').as_posix()}",
    )
    return settings, root


def _old_notes(settings: Settings) -> set[str]:
    """The previous implementation, kept here as the reference behaviour."""
    root = Path(settings.vault.root).resolve()
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and not is_denied(Path(dirpath) / d, settings)
        ]
        for name in filenames:
            p = Path(dirpath) / name
            if (
                not p.name.startswith(".")
                and p.suffix.lower() in NOTE_EXTS
                and not is_denied(p, settings)
            ):
                out.add(p.relative_to(root).as_posix())
    return out


def _old_dirs(settings: Settings) -> set[str]:
    root = Path(settings.vault.root).resolve()
    out: set[str] = set()
    for dirpath, dirnames, _files in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and not is_denied(Path(dirpath) / d, settings)
        ]
        rel = Path(dirpath).relative_to(root).as_posix()
        out.add("" if rel == "." else rel)
    return out


def test_notes_match_previous_walk(messy_vault):
    settings, _root = messy_vault
    new = {rel for _path, rel in _iter_notes(settings)}
    assert new == _old_notes(settings)
    # Spot-check the security-relevant cases explicitly.
    assert "Notes/linked-ok.md" in new
    assert "Notes/linked-denied.md" not in new
    assert not any(rel.startswith("Notes/linked-folder") for rel in new)
    assert not any("private" in rel or rel.startswith(".") for rel in new)
    assert "Notes/.draft.md" not in new and "Notes/image.png" not in new


def test_folders_match_previous_walk(messy_vault):
    settings, _root = messy_vault
    dirs = {rel for kind, rel, _p, _e in walk_vault(settings) if kind == "dir"}
    assert dirs == _old_dirs(settings)
    assert "Empty folder" in dirs


def test_tree_lists_the_same_files(messy_vault):
    settings, _root = messy_vault

    def files(node: dict) -> set[str]:
        if node["type"] == "file":
            return {node["path"]}
        return set().union(*(files(child) for child in node["children"])) if node["children"] else set()

    assert files(list_tree(settings)) == _old_notes(settings)


def test_walk_order_is_top_down_like_os_walk(messy_vault):
    settings, _root = messy_vault
    seen_dirs: list[str] = []
    for kind, rel, _p, _e in walk_vault(settings):
        if kind == "dir":
            seen_dirs.append(rel)
        else:
            parent = rel.rpartition("/")[0]
            assert parent == seen_dirs[-1], "files come right after their folder"
    assert seen_dirs[0] == ""


def test_scopes_skip_hidden_output_and_count_documents(messy_vault):
    settings, root = messy_vault
    db_module.reset_engine()
    db_module.init_db(settings)
    try:
        with session_scope(settings) as session:
            for rel in ["COMP3506 Algorithms/Week 1/w1.md", "Notes/sub/b.md", "Notes/a.md"]:
                session.add(Document(path=str((root / rel).resolve()), title=rel, content_hash=rel))
            session.add(Document(path=str(root.parent / "outside" / "secret.md"), title="o", content_hash="o"))
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            scopes = TestClient(app).get("/scopes").json()["scopes"]
        finally:
            app.dependency_overrides.clear()
    finally:
        db_module.reset_engine()

    by_id = {scope["id"]: scope for scope in scopes}
    assert "folder:StudyCopilot" not in by_id
    assert not any("StudyCopilot" in scope_id for scope_id in by_id)
    assert not any("/." in scope_id or scope_id.startswith("folder:.") for scope_id in by_id)
    assert "folder:Notes/linked-folder" not in by_id
    assert by_id["folder:Notes"]["documents"] == 2
    assert by_id["folder:Notes/sub"]["documents"] == 1
    assert by_id["folder:COMP3506 Algorithms"]["kind"] == "course"
    assert by_id["folder:COMP3506 Algorithms"]["course"] == "COMP3506"
    assert by_id["folder:COMP3506 Algorithms"]["documents"] == 1
    assert by_id["folder:Empty folder"]["documents"] == 0
