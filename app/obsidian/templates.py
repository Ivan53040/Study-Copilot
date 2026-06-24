"""Markdown templates for generated notes.

AI-generated notes carry frontmatter marking them as lower-trust until reviewed
(plan §8) and an explicit banner, so they're never mistaken for source material.
"""

from __future__ import annotations

from datetime import date

import yaml


def render_frontmatter(meta: dict) -> str:
    # sort_keys=False to keep a readable, stable field order.
    body = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{body}\n---"


def revision_note_frontmatter(
    *,
    title: str,
    course: str | None,
    week: int | None,
    derived_from: list[str],
    generated_at: str | None = None,
) -> dict:
    meta: dict = {
        "title": title,
        "course": course,
        "type": "revision-note",
    }
    if week is not None:
        meta["week"] = week
    meta["source_type"] = "ai-generated"
    meta["reviewed_by_user"] = False
    meta["generated_at"] = generated_at or date.today().isoformat()
    if derived_from:
        meta["derived_from"] = derived_from
    return meta


_BANNER = (
    "> [!warning] AI-generated revision note — review before relying on it. "
    "Derived from your own sources; not authoritative until you mark it reviewed."
)


def render_revision_note(
    *,
    frontmatter: dict,
    body: str,
    sources_section: str,
) -> str:
    parts = [
        render_frontmatter(frontmatter),
        "",
        _BANNER,
        "",
        body.strip(),
        "",
        sources_section.strip(),
        "",
    ]
    return "\n".join(parts)
