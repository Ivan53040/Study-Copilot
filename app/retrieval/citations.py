"""Build source citations from search hits (plan §13).

Every grounded answer should cite: document title, course, week, page or
heading, and an Obsidian link / file path. We never invent page numbers — we
only report what the chunk actually carries.
"""

from __future__ import annotations

from pathlib import Path

from app.retrieval.types import SearchHit


def obsidian_link(hit: SearchHit) -> str:
    note = Path(hit.path).stem
    return f"[[{note}]]"


def location(hit: SearchHit) -> str | None:
    if hit.page_number is not None:
        return f"Page {hit.page_number}"
    if hit.heading:
        return f"Section: {hit.heading}"
    return None


def format_citation(hit: SearchHit) -> dict:
    return {
        "title": hit.title,
        "course": hit.course,
        "week": hit.week,
        "location": location(hit),
        "link": obsidian_link(hit),
        "path": hit.path,
        "source_type": hit.source_type,
        "trust_level": hit.trust_level,
    }


def format_citation_markdown(hit: SearchHit) -> str:
    parts = [obsidian_link(hit)]
    loc = location(hit)
    if loc:
        parts.append(loc)
    if hit.course:
        wk = f" Week {hit.week}" if hit.week is not None else ""
        parts.append(f"{hit.course}{wk}")
    return " — ".join(parts)
