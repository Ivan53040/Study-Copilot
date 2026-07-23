"""Phase 9 tests: note workspace (tree, read, edit, graph, safety)."""

from __future__ import annotations

import pytest

from app.security.paths import PathSecurityError
from app.vault.service import (
    build_graph,
    create_folder,
    delete_note,
    export_pdf,
    extract_headings,
    extract_links,
    import_files,
    list_tree,
    list_versions,
    merge_notes,
    move_item,
    open_external,
    read_note,
    rename_note,
    restore_version,
    search_notes,
    set_note_property,
    write_note,
)


@pytest.fixture
def vault(settings):
    root = settings.vault.root
    (root / "A.md").write_text(
        "# A title\n\nLinks to [[B]] and [[Missing]].\n\n## Section\ntext\n",
        encoding="utf-8",
    )
    (root / "B.md").write_text("# B\n\nBack to [[A]].\n", encoding="utf-8")
    return settings


# ---- parsing ----

def test_extract_headings_skips_fenced():
    text = "# Real\n\n```\n# not a heading\n```\n\n## Sub\n"
    heads = extract_headings(text)
    assert [h["text"] for h in heads] == ["Real", "Sub"]
    assert heads[0]["slug"] == "real"


def test_extract_links_variants():
    text = "[[Plain]] [[Target#heading]] [[Target|alias]] [[Plain]]"
    assert extract_links(text) == ["Plain", "Target"]


# ---- tree / read ----

def test_tree_lists_notes(vault):
    tree = list_tree(vault)
    names = _all_files(tree)
    assert "A.md" in names and "B.md" in names
    # Denied/hidden never surface.
    assert not any(".env" in n or ".obsidian" in n for n in names)


def _all_files(node) -> list[str]:
    out = []
    for c in node["children"]:
        if c["type"] == "file":
            out.append(c["path"])
        else:
            out.extend(_all_files(c))
    return out


def test_read_note_links_and_backlinks(vault):
    note = read_note("A.md", vault)
    assert note["name"] == "A title" or note["name"] == "A"
    assert [h["text"] for h in note["headings"]] == ["A title", "Section"]
    # Outgoing links: B resolves, Missing does not.
    resolved = {l["name"]: l["path"] for l in note["links"]}
    assert resolved["B"] == "B.md"
    assert resolved["Missing"] is None

    b = read_note("B.md", vault)
    assert any(bl["path"] == "A.md" for bl in b["backlinks"])


# ---- graph ----

def test_graph_has_edge(vault):
    g = build_graph(vault)
    ids = {n["id"] for n in g["nodes"]}
    assert {"A.md", "B.md"} <= ids
    assert {"source": "A.md", "target": "B.md"} in g["edges"]
    assert g["stats"]["notes"] >= 2


# ---- editing + safety ----

def test_write_note_creates_backup(vault):
    res = write_note("A.md", "# A title\n\nedited body\n", vault)
    assert res["written"] and res["backup"]
    assert read_note("A.md", vault)["content"].strip().endswith("edited body")


def test_backup_versions_are_capped(vault):
    vault.workspace.max_backups_per_note = 2
    for i in range(5):
        write_note("A.md", f"# A title\n\nrevision {i}\n", vault)
    # Pruning keeps at most the cap, so backups can't grow without bound.
    assert len(list_versions("A.md", vault)) <= 2


def test_edit_updates_backlinks(vault):
    # Cache-invalidation check: editing B to drop its [[A]] link must remove
    # A's backlink on the next read (the link graph is mtime/size-cached).
    assert any(bl["path"] == "B.md" for bl in read_note("A.md", vault)["backlinks"])
    write_note("B.md", "# B\n\nno more link.\n", vault)
    assert not any(bl["path"] == "B.md" for bl in read_note("A.md", vault)["backlinks"])


def test_write_blocked_for_denied_and_traversal(vault):
    with pytest.raises(PathSecurityError):
        write_note(".env", "x", vault)
    with pytest.raises(PathSecurityError):
        write_note("../escape.md", "x", vault)


def test_write_blocked_when_edit_disabled(vault):
    vault.workspace.allow_edit = False
    with pytest.raises(PathSecurityError):
        write_note("A.md", "x", vault)


def test_search_notes(vault):
    results = {r["path"] for r in search_notes("a.md", vault)}
    assert "A.md" in results


def test_create_folder_shows_in_tree(vault):
    create_folder("New Folder", vault)
    tree = list_tree(vault)
    folders = _all_folders(tree)
    assert "New Folder" in folders


def _all_folders(node) -> list[str]:
    out = []
    for c in node["children"]:
        if c["type"] == "folder":
            out.append(c["path"])
            out.extend(_all_folders(c))
    return out


def test_create_folder_blocked_when_edit_disabled(vault):
    vault.workspace.allow_edit = False
    with pytest.raises(PathSecurityError):
        create_folder("Nope", vault)


def test_rename_note(vault):
    res = rename_note("A.md", "Renamed/A2.md", vault)
    assert res["to"] == "Renamed/A2.md"
    assert (vault.vault.root / "Renamed" / "A2.md").exists()
    assert not (vault.vault.root / "A.md").exists()


def test_rename_blocked_outside_vault(vault):
    with pytest.raises(PathSecurityError):
        rename_note("A.md", "../escaped.md", vault)


def test_delete_note_is_reversible(vault):
    res = delete_note("B.md", vault)
    assert not (vault.vault.root / "B.md").exists()
    from pathlib import Path

    assert Path(res["backup"]).exists()  # moved to _backups/_deleted


def test_export_pdf(vault):
    res = export_pdf("A.md", vault)
    from pathlib import Path

    pdf = Path(res["pdf"])
    assert pdf.exists() and pdf.suffix == ".pdf" and pdf.stat().st_size > 0


def test_move_file_and_folder(vault):
    create_folder("Destination", vault)
    moved_file = move_item("A.md", "Destination", vault)
    assert moved_file["to"] == "Destination/A.md"
    assert (vault.vault.root / "Destination" / "A.md").exists()

    create_folder("Loose", vault)
    (vault.vault.root / "Loose" / "asset.pdf").write_bytes(b"pdf")
    moved_folder = move_item("Loose", "Destination", vault)
    assert moved_folder["to"] == "Destination/Loose"
    assert (vault.vault.root / "Destination" / "Loose" / "asset.pdf").exists()


def test_import_external_file_and_folder(vault, tmp_path):
    source_file = tmp_path / "lecture.pdf"
    source_file.write_bytes(b"lecture")
    source_folder = tmp_path / "Resources"
    source_folder.mkdir()
    (source_folder / "diagram.png").write_bytes(b"image")

    result = import_files([str(source_file), str(source_folder)], "", vault)
    assert result["count"] == 2
    assert (vault.vault.root / "lecture.pdf").read_bytes() == b"lecture"
    assert (vault.vault.root / "Resources" / "diagram.png").exists()


def test_open_external_search_source(settings, monkeypatch):
    paper = settings.external_sources[0].path / "exam.pdf"
    paper.write_bytes(b"pdf")
    opened: list[str] = []
    monkeypatch.setattr("app.vault.service.os.startfile", opened.append)

    result = open_external(str(paper), settings)

    assert opened == [str(paper.resolve())]
    assert result["opened"] == str(paper.resolve())


def test_merge_property_and_version_restore(vault):
    set_note_property("A.md", "status", "review", vault)
    assert "status: review" in read_note("A.md", vault)["content"]

    merge_notes("A.md", "B.md", False, vault)
    merged = read_note("A.md", vault)["content"]
    assert "Merged from B" in merged
    assert "Back to [[A]]" in merged

    versions = list_versions("A.md", vault)
    assert len(versions) >= 2
    oldest = versions[-1]
    restore_version("A.md", oldest["id"], vault)
    restored = read_note("A.md", vault)["content"]
    assert "Links to [[B]]" in restored
