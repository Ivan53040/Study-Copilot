"""One-off deterministic backlink pass for generated Wiki notes.

Dry-run by default. Pass ``--apply`` to write the changes through the vault
service, which creates the normal per-note backups.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

from app.config.settings import get_settings
from app.vault.links import _frontmatter_end, _mask_line
from app.vault.service import _FENCE_RE, _WIKILINK_RE, write_note

_SPECIAL = {"index.md", "log.md", "purpose.md"}
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")


@dataclass(frozen=True)
class Page:
    path: Path
    rel: str
    course: str
    title: str
    stem: str
    page_type: str
    acronym: bool


def _load_pages(root: Path, vault_root: Path) -> list[Page]:
    pages: list[Page] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() in _SPECIAL:
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            post = frontmatter.loads(raw)
            title = str(post.metadata.get("title") or path.stem).strip()
            page_type = str(post.metadata.get("type") or "concept").lower()
        except Exception:
            title, page_type = path.stem, "concept"
        relative_to_wiki = path.relative_to(root)
        if len(relative_to_wiki.parts) < 2 or not title:
            continue
        compact = re.sub(r"[^A-Za-z0-9]", "", title)
        pages.append(
            Page(
                path=path,
                rel=path.relative_to(vault_root).as_posix(),
                course=relative_to_wiki.parts[0],
                title=title,
                stem=path.stem,
                page_type=page_type,
                acronym=2 <= len(compact) <= 8 and compact.isupper(),
            )
        )
    return pages


def _eligible_target(page: Page) -> bool:
    if page.page_type not in {"concept", "entity"}:
        return False
    words = re.findall(r"[A-Za-z0-9]+", page.title)
    # Short ordinary words are too ambiguous for an unattended pass. Acronyms
    # such as PCA remain eligible, but must match case exactly below.
    return bool(words) and (len(words) > 1 or len(page.title) >= 8 or page.acronym)


def _existing_targets(text: str) -> set[str]:
    existing: set[str] = set()
    for match in _WIKILINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0].strip().replace("\\", "/")
        existing.add(Path(target).name.lower())
    return existing


def _link_for(target: Page, matched: str) -> str:
    return f"[[{target.stem}]]" if matched == target.stem else f"[[{target.stem}|{matched}]]"


def _rewrite(source: Page, targets: dict[str, Page], text: str) -> tuple[str, list[dict]]:
    available = {
        title: page
        for title, page in targets.items()
        if page.rel != source.rel
    }
    existing = _existing_targets(text)
    available = {
        title: page
        for title, page in available.items()
        if page.stem.lower() not in existing and page.title.lower() not in existing
    }
    if not available:
        return text, []

    names = sorted((page.title for page in available.values()), key=len, reverse=True)
    pattern = re.compile(
        rf"(?<![0-9A-Za-z])(?:{'|'.join(re.escape(name) for name in names)})(?![0-9A-Za-z])",
        re.IGNORECASE,
    )
    lines = text.split("\n")
    body_start = _frontmatter_end(lines)
    linked_targets: set[str] = set()
    changes: list[dict] = []
    in_fence = False

    for index, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or index < body_start or _HEADING_RE.match(line):
            continue
        masked = _mask_line(line)
        replacements: list[tuple[int, int, str, Page, str]] = []
        for match in pattern.finditer(masked):
            matched = line[match.start() : match.end()]
            target = available.get(matched.lower())
            if target is None or target.title.lower() in linked_targets:
                continue
            if target.acronym and matched != target.title:
                continue
            replacements.append(
                (match.start(), match.end(), _link_for(target, matched), target, matched)
            )
            linked_targets.add(target.title.lower())
        for start, end, link, target, matched in reversed(replacements):
            line = line[:start] + link + line[end:]
            changes.append(
                {
                    "source": source.rel,
                    "target": target.rel,
                    "title": target.title,
                    "line": index + 1,
                    "matched": matched,
                    "link": link,
                }
            )
        lines[index] = line
    return "\n".join(lines), changes


def run(apply: bool) -> dict:
    settings = get_settings()
    vault_root = Path(settings.vault.root).expanduser().resolve()
    wiki_root = vault_root / settings.wiki.root
    pages = _load_pages(wiki_root, vault_root)

    targets_by_course: dict[str, dict[str, Page]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for page in pages:
        if not _eligible_target(page):
            continue
        course_targets = targets_by_course.setdefault(page.course, {})
        key = page.title.lower()
        if key in course_targets:
            ambiguous.add((page.course, key))
        else:
            course_targets[key] = page
    for course, title in ambiguous:
        targets_by_course[course].pop(title, None)

    all_changes: list[dict] = []
    changed_files = 0
    by_course: dict[str, dict[str, int]] = {}
    for source in pages:
        targets = targets_by_course.get(source.course, {})
        raw = source.path.read_text(encoding="utf-8", errors="replace")
        updated, changes = _rewrite(source, targets, raw)
        if not changes:
            continue
        changed_files += 1
        all_changes.extend(changes)
        stats = by_course.setdefault(source.course, {"files": 0, "links": 0})
        stats["files"] += 1
        stats["links"] += len(changes)
        if apply:
            write_note(source.rel, updated, settings)

    return {
        "mode": "apply" if apply else "dry-run",
        "wiki_files_scanned": len(pages),
        "eligible_targets": sum(len(items) for items in targets_by_course.values()),
        "changed_files": changed_files,
        "links_added": len(all_changes),
        "by_course": by_course,
        "sample": all_changes[:25],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.apply), ensure_ascii=False, indent=2))
