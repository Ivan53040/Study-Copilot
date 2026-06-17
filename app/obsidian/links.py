"""Obsidian link helpers."""

from __future__ import annotations

from pathlib import Path

from app.retrieval.types import SearchHit


def note_name(path: str) -> str:
    """The Obsidian note name (filename without extension) for a path."""
    return Path(path).stem


def wikilink(path: str) -> str:
    return f"[[{note_name(path)}]]"


def derived_from(hits: list[SearchHit]) -> list[str]:
    """Unique source wikilinks, preserving first-seen order (for frontmatter)."""
    seen: list[str] = []
    for h in hits:
        link = wikilink(h.path)
        if link not in seen:
            seen.append(link)
    return seen
