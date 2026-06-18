"""Phase 9 tests: note workspace (tree, read, edit, graph, safety)."""

from __future__ import annotations

import pytest

from app.security.paths import PathSecurityError
from app.vault.service import (
    build_graph,
    extract_headings,
    extract_links,
    list_tree,
    read_note,
    search_notes,
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
