"""Wiki filesystem layer: page paths, frontmatter, index.md, log.md.

All writes go through :func:`app.obsidian.writer.write_note`, which confines
them to ``StudyCopilot/``. ``index.md`` is always regenerated programmatically
from page frontmatter — never written by the LLM — so it cannot drift.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from app.config.settings import Settings
from app.obsidian.templates import render_frontmatter
from app.obsidian.writer import safe_filename, write_note

PAGE_TYPES = ("map", "concept", "entity", "source")
_TYPE_DIRS = {
    "map": "Course Maps",
    "concept": "Concepts",
    "entity": "Entities",
    "source": "Sources",
}
_SPECIAL_FILES = {"index.md", "log.md", "purpose.md"}
_LEADING_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _vault_root(settings: Settings) -> Path:
    return Path(settings.vault.root).expanduser().resolve()


def wiki_course_dir(course: str | None, settings: Settings) -> str:
    """Vault-relative folder holding one course's wiki."""
    return f"{settings.wiki.root}/{safe_filename(course or 'All Courses')}"


def page_rel_path(
    course: str | None, page_type: str, title: str, settings: Settings
) -> str:
    subdir = _TYPE_DIRS.get(page_type, _TYPE_DIRS["concept"])
    return f"{wiki_course_dir(course, settings)}/{subdir}/{safe_filename(title)}.md"


def strip_llm_frontmatter(body: str) -> str:
    """Drop a leading ``---`` block if the model emitted one; we own frontmatter."""
    return _LEADING_FRONTMATTER_RE.sub("", body.lstrip()).strip()


def read_wiki_page(rel: str, settings: Settings) -> dict | None:
    path = _vault_root(settings) / rel
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        post = frontmatter.loads(raw)
        meta, body = dict(post.metadata), post.content
    except Exception:
        meta, body = {}, raw
    return {
        "path": rel.replace("\\", "/"),
        "title": str(meta.get("title") or path.stem),
        "type": str(meta.get("type") or "concept"),
        "course": meta.get("course"),
        "sources": [str(s) for s in (meta.get("sources") or [])],
        "aliases": [str(a) for a in (meta.get("aliases") or [])],
        "summary": str(meta.get("summary") or ""),
        "updated_at": str(meta.get("updated_at") or ""),
        "body": body.strip(),
    }


def list_wiki_pages(course: str | None, settings: Settings) -> list[dict]:
    root = _vault_root(settings)
    base = root / wiki_course_dir(course, settings)
    if course is None:
        base = root / settings.wiki.root
    if not base.is_dir():
        return []
    pages: list[dict] = []
    for path in sorted(base.rglob("*.md")):
        if path.name.lower() in _SPECIAL_FILES:
            continue
        rel = path.relative_to(root).as_posix()
        page = read_wiki_page(rel, settings)
        if page is not None:
            pages.append(page)
    return pages


def find_existing_page(
    course: str | None, title: str, settings: Settings
) -> dict | None:
    """Look up a durable wiki page by title or alias.

    Source summaries are deliberately excluded: a lecture named ``Functions``
    must not shadow the canonical ``Function`` concept during a rebuild.
    """
    for page_type in ("map", "concept", "entity"):
        page = read_wiki_page(page_rel_path(course, page_type, title, settings), settings)
        if page is not None:
            return page
    wanted = title.strip().lower()
    for page in list_wiki_pages(course, settings):
        if page["type"] == "source":
            continue
        if wanted in {page["title"].lower(), *(alias.lower() for alias in page["aliases"])}:
            return page
    return None


def write_page(
    rel: str, meta: dict, body: str, settings: Settings
) -> None:
    content = f"{render_frontmatter(meta)}\n\n{strip_llm_frontmatter(body)}\n"
    write_note(rel, content, settings, overwrite=True)


def render_index(course: str | None, pages: list[dict]) -> str:
    lines = [f"# Wiki Index — {course or 'All Courses'}", ""]
    for page_type, heading in (
        ("map", "Course Maps"),
        ("concept", "Concepts"),
        ("entity", "Entities"),
        ("source", "Sources"),
    ):
        group = [p for p in pages if p["type"] == page_type]
        if not group:
            continue
        lines.append(f"## {heading}")
        lines.append("")
        for page in sorted(group, key=lambda p: p["title"].lower()):
            summary = f" — {page['summary']}" if page["summary"] else ""
            lines.append(f"- [[{page['title']}]]{summary}")
        lines.append("")
    if len(lines) == 2:
        lines.append("*(empty — run a wiki build)*")
    return "\n".join(lines).rstrip() + "\n"


def write_index(course: str | None, settings: Settings) -> str:
    rel = f"{wiki_course_dir(course, settings)}/index.md"
    write_note(rel, render_index(course, list_wiki_pages(course, settings)), settings)
    return rel


def index_excerpt_for_prompt(course: str | None, settings: Settings) -> str:
    """Index text for prompts, dropping Sources first when over budget."""
    pages = list_wiki_pages(course, settings)
    limit = settings.wiki.max_index_chars
    text = render_index(course, pages)
    if len(text) > limit:
        text = render_index(course, [p for p in pages if p["type"] != "source"])
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n[truncated]"
    return text


def append_log(course: str | None, entry: dict, settings: Settings) -> None:
    """Append one parseable ``key=value`` line to the course's log.md."""
    rel = f"{wiki_course_dir(course, settings)}/log.md"
    path = _vault_root(settings) / rel
    existing = (
        path.read_text(encoding="utf-8", errors="replace")
        if path.is_file()
        else "# Wiki Log\n\n"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fields = " | ".join(f"{key}={value}" for key, value in entry.items())
    write_note(rel, f"{existing.rstrip()}\n- {stamp} | {fields}\n", settings)


def read_purpose(course: str | None, settings: Settings) -> str | None:
    rel = f"{wiki_course_dir(course, settings)}/purpose.md"
    path = _vault_root(settings) / rel
    if not path.is_file():
        return None
    try:
        body = frontmatter.loads(
            path.read_text(encoding="utf-8", errors="replace")
        ).content.strip()
    except Exception:
        body = path.read_text(encoding="utf-8", errors="replace").strip()
    return body or None


def has_purpose(course: str | None, settings: Settings) -> bool:
    return (_vault_root(settings) / wiki_course_dir(course, settings) / "purpose.md").is_file()
