"""Filesystem-backed note workspace: tree, read, edit, link graph.

This is independent of the RAG index — it reads notes straight from disk so the
app can act as a standalone Obsidian-style workspace. All access goes through the
workspace path-security helpers, so denied paths stay off-limits and edits are
confined to text notes inside the vault.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger
from app.security.paths import (
    assert_workspace_readable,
    assert_workspace_writable,
    is_denied,
)

logger = get_logger("vault")

NOTE_EXTS = {".md", ".markdown", ".txt"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# [[Target]], [[Target#heading]], [[Target|alias]]
_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
_BACKUP_DIR = "StudyCopilot/_backups"


def _vault_root(settings: Settings) -> Path:
    return Path(settings.vault.root).expanduser().resolve()


def _iter_notes(settings: Settings):
    root = _vault_root(settings)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and not is_denied(Path(dirpath) / d, settings)
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() in NOTE_EXTS and not is_denied(p, settings):
                yield p, p.relative_to(root).as_posix()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def extract_headings(text: str) -> list[dict]:
    out: list[dict] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_RE.match(line)
        if m:
            heading = m.group(2).strip()
            out.append(
                {"level": len(m.group(1)), "text": heading, "slug": _slugify(heading)}
            )
    return out


def extract_links(text: str) -> list[str]:
    seen: list[str] = []
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if target and target not in seen:
            seen.append(target)
    return seen


def list_tree(settings: Settings | None = None) -> dict:
    """Nested folder/file tree of notes under the vault root."""
    settings = settings or get_settings()
    root: dict = {"name": "", "path": "", "type": "folder", "children": {}}

    for _, rel in _iter_notes(settings):
        parts = rel.split("/")
        node = root
        for part in parts[:-1]:
            child = node["children"].get(part)
            if child is None:
                child = {
                    "name": part,
                    "path": "/".join(
                        rel.split("/")[: parts.index(part) + 1]
                    ),
                    "type": "folder",
                    "children": {},
                }
                node["children"][part] = child
            node = child
        node["children"][parts[-1]] = {
            "name": parts[-1],
            "path": rel,
            "type": "file",
        }

    def to_list(node: dict) -> dict:
        children = node["children"].values()
        folders = sorted(
            (to_list(c) for c in children if c["type"] == "folder"),
            key=lambda c: c["name"].lower(),
        )
        files = sorted(
            (c for c in children if c["type"] == "file"),
            key=lambda c: c["name"].lower(),
        )
        return {
            "name": node["name"],
            "path": node["path"],
            "type": "folder",
            "children": folders + files,
        }

    return to_list(root)


def _note_index(settings: Settings) -> dict[str, str]:
    """Map lowercased note name (stem) -> relpath, for link resolution."""
    index: dict[str, str] = {}
    for _, rel in _iter_notes(settings):
        stem = Path(rel).stem.lower()
        index.setdefault(stem, rel)
    return index


def read_note(relpath: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    abs_path = assert_workspace_readable(_vault_root(settings) / relpath, settings)
    if not abs_path.exists():
        raise FileNotFoundError(f"Note not found: {relpath}")

    raw = abs_path.read_text(encoding="utf-8", errors="replace")
    try:
        post = frontmatter.loads(raw)
        meta, body = dict(post.metadata), post.content
    except Exception:
        meta, body = {}, raw

    links = extract_links(raw)
    index = _note_index(settings)
    resolved = [
        {"name": n, "path": index.get(n.lower())} for n in links
    ]

    # Backlinks: any note whose body links to this note's name.
    this_stem = Path(relpath).stem.lower()
    backlinks: list[dict] = []
    for p, rel in _iter_notes(settings):
        if rel == relpath:
            continue
        try:
            other = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(l.lower() == this_stem for l in extract_links(other)):
            backlinks.append({"path": rel, "title": Path(rel).stem})

    return {
        "path": relpath,
        "name": Path(relpath).stem,
        "content": raw,
        "frontmatter": meta,
        "headings": extract_headings(body),
        "links": resolved,
        "backlinks": backlinks,
        "editable": abs_path.suffix.lower()
        in set(settings.workspace.editable_extensions),
    }


def write_note(
    relpath: str, content: str, settings: Settings | None = None
) -> dict:
    settings = settings or get_settings()
    abs_path = assert_workspace_writable(_vault_root(settings) / relpath, settings)

    backup_path = None
    if settings.workspace.backup_on_edit and abs_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup = (
            _vault_root(settings) / _BACKUP_DIR / f"{relpath}.{stamp}.bak"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(
            abs_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
        )
        backup_path = str(backup)

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    logger.info("Edited note %s (backup=%s)", relpath, bool(backup_path))
    return {"path": relpath, "written": True, "backup": backup_path}


def build_graph(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    index = _note_index(settings)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for p, rel in _iter_notes(settings):
        node_id = rel
        folder = rel.split("/")[0] if "/" in rel else ""
        nodes.setdefault(
            node_id,
            {"id": node_id, "title": Path(rel).stem, "folder": folder, "degree": 0},
        )
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for link in extract_links(text):
            target_rel = index.get(link.lower())
            if target_rel and target_rel != rel:
                edges.append({"source": rel, "target": target_rel})

    for e in edges:
        nodes[e["source"]]["degree"] += 1
        if e["target"] in nodes:
            nodes[e["target"]]["degree"] += 1

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {"notes": len(nodes), "links": len(edges)},
    }


def search_notes(
    query: str, settings: Settings | None = None, limit: int = 30
) -> list[dict]:
    settings = settings or get_settings()
    q = query.lower().strip()
    out: list[dict] = []
    for _, rel in _iter_notes(settings):
        if not q or q in rel.lower():
            out.append({"path": rel, "title": Path(rel).stem})
            if len(out) >= limit:
                break
    return out
