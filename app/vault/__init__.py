"""Standalone note workspace over the whole vault (browse, edit, graph)."""

from app.vault.service import (
    build_graph,
    list_tree,
    read_note,
    search_notes,
    write_note,
)

__all__ = [
    "build_graph",
    "list_tree",
    "read_note",
    "search_notes",
    "write_note",
]
