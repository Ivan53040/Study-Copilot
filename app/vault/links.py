"""Backlinks and unlinked mentions for the note workspace (Obsidian-style).

For a given note this scans every other note in the vault for:
  - linked mentions: wikilinks whose target resolves to this note's name
  - unlinked mentions: the note's name appearing as plain text (outside links,
    code, and frontmatter), which the UI can convert into a wikilink

Note text is cached per-file by (mtime, size), so repeat requests do a
stat-only walk instead of re-reading the whole vault.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Callable

from app.config.settings import Settings, get_settings
from app.generation.jsonparse import extract_json
from app.models.chat import ChatError, ChatMessage, get_chat_adapter
from app.security.paths import assert_workspace_readable
from app.vault.service import (
    _FENCE_RE,
    _WIKILINK_RE,
    _iter_notes,
    _vault_root,
    search_notes,
    write_note,
)

_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_SNIPPET_MAX = 180
_AI_CANDIDATE_LIMIT = 80
_AI_WIKI_CONTEXT_LIMIT = 12_000
_RELEVANT_LINE_RE = re.compile(r"(?:final\s+)?relevant\s*:\s*([^\r\n]+)", re.IGNORECASE)

_CACHE_LOCK = threading.Lock()
_TEXT_CACHE: dict = {"root": None, "texts": {}}  # rel -> (mtime_ns, size, text)


def _vault_texts(settings: Settings) -> dict[str, str]:
    """Full text of every note in the vault, cached by (mtime, size)."""
    root = str(_vault_root(settings))
    with _CACHE_LOCK:
        snapshot = dict(_TEXT_CACHE["texts"]) if _TEXT_CACHE["root"] == root else {}

    texts: dict[str, str] = {}
    fresh: dict[str, tuple[int, int, str]] = {}
    for path, rel in _iter_notes(settings):
        try:
            stat = path.stat()
        except OSError:
            continue
        cached = snapshot.get(rel)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            texts[rel] = cached[2]
            fresh[rel] = cached
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texts[rel] = text
        fresh[rel] = (stat.st_mtime_ns, stat.st_size, text)

    with _CACHE_LOCK:
        _TEXT_CACHE.update(root=root, texts=fresh)
    return texts


def _blank(match: re.Match) -> str:
    return " " * len(match.group(0))


def _mask_line(line: str) -> str:
    """Blank out spans where a plain-text match must not count as a mention."""
    line = _WIKILINK_RE.sub(_blank, line)
    line = _INLINE_CODE_RE.sub(_blank, line)
    return _MD_LINK_RE.sub(_blank, line)


def _snippet(line: str, start: int, end: int) -> dict:
    """A display window around a match, with highlight offsets into it."""
    lead = len(line) - len(line.lstrip())
    text = line.strip()
    s, e = start - lead, end - lead
    if len(text) > _SNIPPET_MAX:
        window_start = max(0, s - 50)
        window_end = min(len(text), window_start + _SNIPPET_MAX)
        prefix = "…" if window_start > 0 else ""
        suffix = "…" if window_end < len(text) else ""
        s = s - window_start + len(prefix)
        e = e - window_start + len(prefix)
        text = prefix + text[window_start:window_end] + suffix
    s = max(0, min(s, len(text)))
    e = max(s, min(e, len(text)))
    return {"snippet": text, "hl_start": s, "hl_end": e}


def _frontmatter_end(lines: list[str]) -> int:
    """Index of the first body line, past a leading ``---`` frontmatter block."""
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


def _mention_names(relpath: str, aliases: list[str] | None = None) -> list[str]:
    names: list[str] = []
    for name in [Path(relpath).stem, *(aliases or [])]:
        clean = name.strip()
        if len(clean) >= 2 and clean.lower() not in {n.lower() for n in names}:
            names.append(clean)
    return names


def _mention_patterns(names: list[str]) -> list[tuple[str, re.Pattern]]:
    return [
        (
            name,
            re.compile(
                rf"(?<![0-9A-Za-z]){re.escape(name)}(?![0-9A-Za-z])",
                re.IGNORECASE,
            ),
        )
        for name in sorted(names, key=len, reverse=True)
    ]


def get_mentions(
    relpath: str,
    settings: Settings | None = None,
    aliases: list[str] | None = None,
) -> dict:
    """Linked + unlinked mentions of a note across the vault, with snippets."""
    settings = settings or get_settings()
    abs_path = assert_workspace_readable(_vault_root(settings) / relpath, settings)
    if not abs_path.exists():
        raise FileNotFoundError(f"Note not found: {relpath}")

    stem = Path(relpath).stem
    names = _mention_names(relpath, aliases)
    name_lowers = {name.lower() for name in names}
    # Custom word boundaries: titles can start/end with non-word characters.
    mention_res = _mention_patterns(names)

    linked: list[dict] = []
    unlinked: list[dict] = []
    for rel, text in sorted(_vault_texts(settings).items()):
        if rel == relpath:
            continue
        lines = text.split("\n")
        body_start = _frontmatter_end(lines)
        linked_mentions: list[dict] = []
        unlinked_mentions: list[dict] = []
        in_fence = False
        for idx, line in enumerate(lines):
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in _WIKILINK_RE.finditer(line):
                if m.group(1).strip().lower() in name_lowers:
                    linked_mentions.append(
                        {"line": idx + 1, "start": m.start(), "end": m.end()}
                        | _snippet(line, m.start(), m.end())
                    )
            if not mention_res or idx < body_start:
                continue
            masked = _mask_line(line)
            seen_spans: set[tuple[int, int]] = set()
            for _, mention_re in mention_res:
                for m in mention_re.finditer(masked):
                    span = (m.start(), m.end())
                    if span in seen_spans:
                        continue
                    seen_spans.add(span)
                    unlinked_mentions.append(
                        {"line": idx + 1, "start": m.start(), "end": m.end()}
                        | _snippet(line, m.start(), m.end())
                    )
            unlinked_mentions.sort(key=lambda item: (item["line"], item["start"]))
        group = {"path": rel, "title": Path(rel).stem}
        if linked_mentions:
            linked.append(group | {"mentions": linked_mentions})
        if unlinked_mentions:
            unlinked.append(group | {"mentions": unlinked_mentions})

    return {"path": relpath, "name": stem, "linked": linked, "unlinked": unlinked}


def _wiki_context(settings: Settings, target_rel: str) -> str:
    """Compact catalogue of all wiki pages for semantic disambiguation."""
    from app.wiki.store import list_wiki_pages

    entries: list[str] = []
    used = 0
    for page in list_wiki_pages(None, settings):
        if page["path"] == target_rel:
            continue
        summary = page["summary"].replace("\n", " ").strip()
        entry = f"- {page['title']} ({page['type']}): {summary}".rstrip()
        if used + len(entry) + 1 > _AI_WIKI_CONTEXT_LIMIT:
            entries.append("[remaining wiki pages omitted]")
            break
        entries.append(entry)
        used += len(entry) + 1
    return "\n".join(entries) or "[no other wiki pages]"


def _parse_ai_review(text: str) -> tuple[dict, str | None]:
    """Accept strict JSON, or a simple ``RELEVANT: c1, c4`` model response."""
    try:
        parsed = extract_json(text)
        if isinstance(parsed, dict):
            return parsed, None
    except ValueError:
        pass

    line = _RELEVANT_LINE_RE.search(text)
    if line:
        ids = re.findall(r"\bc\d+\b", line.group(1), flags=re.IGNORECASE)
        return {
            "relevant": [
                {
                    "id": candidate_id.lower(),
                    "reason": "Selected by the local model.",
                    "confidence": 0.7,
                }
                for candidate_id in dict.fromkeys(ids)
            ]
        }, None
    return {"relevant": []}, "The local model did not return usable link choices."


def review_mentions_with_ai(
    relpath: str,
    settings: Settings | None = None,
    aliases: list[str] | None = None,
) -> dict:
    """Return only high-confidence source mentions selected by the local model.

    The model can select existing candidates only. Actual edits remain explicit
    user approvals through :func:`link_mention`.
    """
    settings = settings or get_settings()
    mentions = get_mentions(relpath, settings, aliases=aliases)
    candidates: list[dict] = []
    for group in mentions["unlinked"]:
        for mention in group["mentions"]:
            if len(candidates) >= _AI_CANDIDATE_LIMIT:
                break
            candidates.append(
                {
                    "id": f"c{len(candidates)}",
                    "path": group["path"],
                    "line": mention["line"],
                    "start": mention["start"],
                    "end": mention["end"],
                    "snippet": mention["snippet"],
                }
            )
        if len(candidates) >= _AI_CANDIDATE_LIMIT:
            break
    if not candidates:
        return mentions | {"model": None, "reviewed": 0, "candidates": 0}

    target_text = assert_workspace_readable(
        _vault_root(settings) / relpath, settings
    ).read_text(encoding="utf-8", errors="replace")
    target_name = (aliases or [Path(relpath).stem])[0]
    prompt = (
        f"Selected wiki page: {target_name}\nPath: {relpath}\n\n"
        "Selected page content:\n"
        f"{target_text[:settings.wiki.max_existing_page_chars]}\n\n"
        "Other wiki pages (context only; do not link to these):\n"
        f"{_wiki_context(settings, relpath)}\n\n"
        "Candidate source mentions. Select only candidates where the surrounding "
        "text is genuinely about the selected wiki page, not a different meaning "
        "or a passing unrelated use. Respond with exactly one of these formats:\n"
        '1. {"relevant":[{"id":"c0","reason":"short reason","confidence":0.9}]}\n'
        "2. RELEVANT: c0, c4\n"
        "Use only candidate IDs. Include only high-confidence candidates. Never "
        "make up IDs.\n\nCandidates:\n"
        + "\n".join(
            f"{item['id']} | {item['path']}:{item['line']} | {item['snippet']}"
            for item in candidates
        )
    )
    try:
        adapter = get_chat_adapter(
            settings, task="wiki", timeout=settings.wiki.chat_timeout_seconds
        )
        response = adapter.generate(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "You review proposed backlinks in a study wiki. Be "
                        "conservative: false positives are worse than omissions. "
                        "Do not show reasoning."
                    ),
                ),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=5000,
        )
        raw, notice = _parse_ai_review(response.content)
    except ChatError as exc:
        raise RuntimeError(f"AI backlink review failed: {exc}") from exc

    selected: dict[str, dict] = {}
    if isinstance(raw, dict) and isinstance(raw.get("relevant"), list):
        for item in raw["relevant"]:
            if not isinstance(item, dict):
                continue
            candidate = next((c for c in candidates if c["id"] == item.get("id")), None)
            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            if candidate is not None and confidence >= 0.7:
                selected[candidate["id"]] = {
                    "reason": str(item.get("reason", "Relevant to this wiki page.")).strip(),
                    "confidence": confidence,
                }

    selected_locations = {
        (candidate["path"], candidate["line"], candidate["start"], candidate["end"]): selected[candidate["id"]]
        for candidate in candidates
        if candidate["id"] in selected
    }
    reviewed_groups: list[dict] = []
    for group in mentions["unlinked"]:
        kept = [
            mention | selected_locations[(group["path"], mention["line"], mention["start"], mention["end"])]
            for mention in group["mentions"]
            if (group["path"], mention["line"], mention["start"], mention["end"]) in selected_locations
        ]
        if kept:
            reviewed_groups.append(group | {"mentions": kept})

    return mentions | {
        "unlinked": reviewed_groups,
        "model": adapter.model_name,
        "reviewed": len(selected),
        "candidates": len(candidates),
        "notice": notice,
    }


def review_wiki_backlinks(
    course: str | None,
    settings: Settings | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Review every concept/entity in a wiki scope without writing links."""
    from app.wiki.store import list_wiki_pages

    settings = settings or get_settings()
    pages = [
        page
        for page in list_wiki_pages(course, settings)
        if page["type"] in {"concept", "entity"}
    ]
    targets: list[dict] = []
    errors: list[dict] = []
    total = len(pages)
    for current, page in enumerate(pages, start=1):
        if progress:
            progress(current - 1, total, f"Reviewing {page['title']}...")
        try:
            review = review_mentions_with_ai(
                page["path"], settings, aliases=[page["title"]]
            )
        except (FileNotFoundError, PathSecurityError, RuntimeError) as exc:
            errors.append({"path": page["path"], "title": page["title"], "error": str(exc)})
            continue
        if review["unlinked"]:
            targets.append(
                {
                    "path": page["path"],
                    "title": page["title"],
                    "aliases": [page["title"]],
                    "review": review,
                }
            )
    if progress:
        progress(total, total, "AI link review complete.")
    return {
        "course": course,
        "targets": targets,
        "pages_reviewed": total,
        "suggestions": sum(
            len(group["mentions"])
            for target in targets
            for group in target["review"]["unlinked"]
        ),
        "errors": errors,
    }


def search_backlink_candidates(
    query: str,
    settings: Settings | None = None,
    *,
    target_limit: int = 8,
    mention_limit: int = 80,
) -> dict:
    """Find unlinked mention candidates for matching target notes.

    This is intentionally query-driven. It gives the UI a review queue for a
    concept/title the user is actively looking for, instead of mass-linking the
    vault automatically.
    """
    settings = settings or get_settings()
    q = query.strip()
    if len(q) < 2:
        return {"query": query, "targets": [], "count": 0, "mentions": 0}

    q_lower = q.lower()

    def rank(item: dict) -> tuple[int, str]:
        title = item["title"].lower()
        path = item["path"].lower()
        if title == q_lower:
            bucket = 0
        elif title.startswith(q_lower):
            bucket = 1
        elif q_lower in title:
            bucket = 2
        elif q_lower in path:
            bucket = 3
        else:
            bucket = 4
        return bucket, item["title"].lower()

    targets = sorted(search_notes(q, settings, limit=target_limit * 4), key=rank)
    results: list[dict] = []
    total_mentions = 0
    for target in targets:
        if len(results) >= target_limit or total_mentions >= mention_limit:
            break
        mentions = get_mentions(target["path"], settings)
        groups: list[dict] = []
        target_mentions = 0
        for group in mentions["unlinked"]:
            remaining = mention_limit - total_mentions
            if remaining <= 0:
                break
            clipped = group["mentions"][:remaining]
            if not clipped:
                continue
            groups.append(group | {"mentions": clipped})
            target_mentions += len(clipped)
            total_mentions += len(clipped)
        if groups:
            results.append(
                {
                    "path": target["path"],
                    "title": target["title"],
                    "name": mentions["name"],
                    "unlinked": groups,
                    "count": target_mentions,
                }
            )

    return {
        "query": query,
        "targets": results,
        "count": len(results),
        "mentions": total_mentions,
    }


def link_mention(
    source_rel: str,
    target_rel: str,
    line: int,
    start: int,
    end: int,
    settings: Settings | None = None,
    aliases: list[str] | None = None,
) -> dict:
    """Convert a plain-text mention in ``source_rel`` into a wikilink.

    ``line``/``start``/``end`` must come from a fresh :func:`get_mentions`
    result; the matched text is re-validated so a stale panel can't corrupt
    the note.
    """
    settings = settings or get_settings()
    stem = Path(target_rel).stem
    name_lowers = {name.lower() for name in _mention_names(target_rel, aliases)}
    abs_path = assert_workspace_readable(_vault_root(settings) / source_rel, settings)
    if not abs_path.exists():
        raise FileNotFoundError(f"Note not found: {source_rel}")

    lines = abs_path.read_text(encoding="utf-8", errors="replace").split("\n")
    if not 1 <= line <= len(lines):
        raise ValueError("Mention is out of date; refresh and try again.")
    text = lines[line - 1]
    matched = text[start:end]
    if matched.lower() not in name_lowers:
        raise ValueError("Mention is out of date; refresh and try again.")

    # Same-name text links directly; otherwise alias so the display text stays.
    link = f"[[{matched}]]" if matched == stem else f"[[{stem}|{matched}]]"
    lines[line - 1] = text[:start] + link + text[end:]
    return write_note(source_rel, "\n".join(lines), settings) | {"link": link}
