"""Filesystem-backed note workspace: tree, read, edit, link graph.

This is independent of the RAG index — it reads notes straight from disk so the
app can act as a standalone Obsidian-style workspace. All access goes through the
workspace path-security helpers, so denied paths stay off-limits and edits are
confined to text notes inside the vault.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import json
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from app.config.settings import Settings, get_settings
from app.logging_config import get_logger
from app.security.paths import (
    PathSecurityError,
    assert_readable,
    assert_workspace_readable,
    assert_workspace_writable,
    is_denied,
    is_in_vault,
)

logger = get_logger("vault")

NOTE_EXTS = {".md", ".markdown", ".txt"}
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# [[Target]], [[Target#heading]], [[Target|alias]]
_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:[#\|][^\]]*)?\]\]")
_BACKUP_DIR = "StudyCopilot/_backups"

# Cached name-index + outgoing-links-per-note for the whole vault, so opening a
# note doesn't re-read every other note. Invalidated by a cheap stat signature.
_GRAPH_LOCK = threading.Lock()
_GRAPH_CACHE: dict = {"root": None, "sig": None, "index": {}, "outlinks": {}}


def _vault_root(settings: Settings) -> Path:
    return Path(settings.vault.root).expanduser().resolve()


def _visible_dirs(dirpath: str, dirnames: list[str], settings: Settings) -> list[str]:
    """Subdirectories worth descending into: skip hidden and denied folders."""
    return [
        d
        for d in dirnames
        if not d.startswith(".") and not is_denied(Path(dirpath) / d, settings)
    ]


def _is_note_file(p: Path, settings: Settings) -> bool:
    """A visible, allowed file with a recognised note extension."""
    return (
        not p.name.startswith(".")
        and p.suffix.lower() in NOTE_EXTS
        and not is_denied(p, settings)
    )


def _iter_notes(settings: Settings):
    root = _vault_root(settings)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = _visible_dirs(dirpath, dirnames, settings)
        for name in filenames:
            p = Path(dirpath) / name
            if _is_note_file(p, settings):
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
    """Nested folder/file tree of the vault (includes empty folders)."""
    settings = settings or get_settings()
    root_path = _vault_root(settings)
    root: dict = {"name": "", "path": "", "type": "folder", "children": {}}

    def ensure_folder(rel: str) -> dict:
        node = root
        if not rel:
            return node
        acc: list[str] = []
        for part in rel.split("/"):
            acc.append(part)
            child = node["children"].get(part)
            if child is None:
                child = {
                    "name": part,
                    "path": "/".join(acc),
                    "type": "folder",
                    "children": {},
                }
                node["children"][part] = child
            node = child
        return node

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = _visible_dirs(dirpath, dirnames, settings)
        rel_dir = Path(dirpath).relative_to(root_path).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        folder = ensure_folder(rel_dir)
        for name in filenames:
            p = Path(dirpath) / name
            if _is_note_file(p, settings):
                folder["children"][name] = {
                    "name": name,
                    "path": p.relative_to(root_path).as_posix(),
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


def _link_graph(settings: Settings) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Return ``(name_index, outgoing_links_per_note)`` for the whole vault.

    Cached and invalidated by a stat signature (path + mtime + size of every
    note), so repeat opens do a stat-only walk instead of reading every note's
    content each time.
    """
    root = str(_vault_root(settings))
    entries: list[tuple[str, Path, int, int]] = []
    for path, rel in _iter_notes(settings):
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append((rel, path, stat.st_mtime_ns, stat.st_size))
    signature = tuple(sorted((rel, mtime, size) for rel, _p, mtime, size in entries))

    with _GRAPH_LOCK:
        if _GRAPH_CACHE["root"] == root and _GRAPH_CACHE["sig"] == signature:
            return _GRAPH_CACHE["index"], _GRAPH_CACHE["outlinks"]

    index: dict[str, str] = {}
    outlinks: dict[str, list[str]] = {}
    for rel, path, _mtime, _size in entries:
        index.setdefault(Path(rel).stem.lower(), rel)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            outlinks[rel] = []
            continue
        outlinks[rel] = extract_links(text)

    with _GRAPH_LOCK:
        _GRAPH_CACHE.update(root=root, sig=signature, index=index, outlinks=outlinks)
    return index, outlinks


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

    index, outlinks = _link_graph(settings)
    # Resolve this note's outgoing links from its freshly-read content.
    resolved = [
        {"name": n, "path": index.get(n.lower())} for n in extract_links(raw)
    ]

    # Backlinks: any other note whose body links to this note's name.
    this_stem = Path(relpath).stem.lower()
    backlinks: list[dict] = [
        {"path": rel, "title": Path(rel).stem}
        for rel, targets in outlinks.items()
        if rel != relpath and any(t.lower() == this_stem for t in targets)
    ]

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


def _prune_backups(backup_dir: Path, note_name: str, settings: Settings) -> None:
    """Keep only the newest ``max_backups_per_note`` ``.bak`` files for a note."""
    keep = settings.workspace.max_backups_per_note
    if keep <= 0:  # 0 (or negative) means unlimited history
        return
    backups = sorted(
        backup_dir.glob(f"{note_name}.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[keep:]:
        try:
            stale.unlink()
        except OSError:
            logger.warning("Could not prune old backup %s", stale)


def write_note(
    relpath: str, content: str, settings: Settings | None = None
) -> dict:
    settings = settings or get_settings()
    root = _vault_root(settings)
    abs_path = assert_workspace_writable(root / relpath, settings)

    backup_path = None
    if settings.workspace.backup_on_edit and abs_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        backup = root / _BACKUP_DIR / f"{relpath}.{stamp}.bak"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(
            abs_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8"
        )
        backup_path = str(backup)
        _prune_backups(backup.parent, Path(relpath).name, settings)

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(content, encoding="utf-8")
    logger.info("Edited note %s (backup=%s)", relpath, bool(backup_path))
    return {"path": relpath, "written": True, "backup": backup_path}


def create_folder(relpath: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    if not settings.workspace.allow_edit:
        raise PathSecurityError("Editing is disabled.")
    p = (_vault_root(settings) / relpath).expanduser().resolve()
    if not is_in_vault(p, settings):
        raise PathSecurityError(f"Folder not allowed: {relpath}")
    p.mkdir(parents=True, exist_ok=True)
    return {"path": relpath, "created": True}


def _rewrite_links_to(from_rel: str, to_rel: str, settings: Settings) -> int:
    """Retarget every ``[[wikilink]]`` after a rename; returns notes changed.

    Preserves ``#heading`` and ``|alias`` parts, and the ``!`` of embeds,
    because only the ``[[Name`` prefix is rewritten. Notes that are not
    editable (per workspace rules) are left untouched.
    """
    old_stem, new_stem = Path(from_rel).stem, Path(to_rel).stem
    if old_stem == new_stem:
        return 0
    pattern = re.compile(
        rf"\[\[\s*{re.escape(old_stem)}\s*(?=[\]#|])", re.IGNORECASE
    )
    changed = 0
    for path, rel in _iter_notes(settings):
        if rel == to_rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        new_text, hits = pattern.subn(lambda _m: f"[[{new_stem}", text)
        if not hits:
            continue
        try:
            write_note(rel, new_text, settings)
            changed += 1
        except PathSecurityError:
            continue
    return changed


def rename_note(
    from_rel: str, to_rel: str, settings: Settings | None = None
) -> dict:
    """Rename/move a note within the vault (text files only).

    When the note's name changes, wikilinks across the vault are retargeted
    to the new name (Obsidian's "update internal links" behavior).
    """
    settings = settings or get_settings()
    root = _vault_root(settings)
    src = assert_workspace_writable(root / from_rel, settings)
    if not src.exists():
        raise FileNotFoundError(f"Note not found: {from_rel}")
    dst = assert_workspace_writable(root / to_rel, settings)
    if dst.exists():
        raise FileExistsError(f"Target already exists: {to_rel}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    new_rel = dst.relative_to(root).as_posix()
    links_updated = _rewrite_links_to(from_rel, new_rel, settings)
    logger.info(
        "Renamed note %s -> %s (links updated in %d notes)",
        from_rel,
        new_rel,
        links_updated,
    )
    return {"from": from_rel, "to": new_rel, "links_updated": links_updated}


def move_item(
    from_rel: str, to_folder: str, settings: Settings | None = None
) -> dict:
    """Move a file or folder to another folder while preserving its name."""
    settings = settings or get_settings()
    if not settings.workspace.allow_edit:
        raise PathSecurityError("Editing is disabled.")
    root = _vault_root(settings)
    src = assert_workspace_readable(root / from_rel, settings)
    folder = (root / to_folder).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Path not found: {from_rel}")
    if not folder.is_dir() or not is_in_vault(folder, settings):
        raise PathSecurityError(f"Destination folder not allowed: {to_folder}")
    if src == root or "StudyCopilot" in src.relative_to(root).parts:
        raise PathSecurityError("System folders cannot be moved.")
    dst = folder / src.name
    if dst.exists():
        raise FileExistsError(f"Target already exists: {dst.relative_to(root)}")
    if src.is_dir():
        try:
            dst.relative_to(src)
            raise PathSecurityError("A folder cannot be moved inside itself.")
        except ValueError:
            pass
    elif src.suffix.lower() in NOTE_EXTS:
        assert_workspace_writable(src, settings)
    shutil.move(str(src), str(dst))
    return {
        "from": from_rel,
        "to": dst.relative_to(root).as_posix(),
        "type": "folder" if dst.is_dir() else "file",
    }


def import_files(
    source_paths: list[str],
    target_folder: str = "",
    settings: Settings | None = None,
) -> dict:
    """Copy user-dropped files/directories into a vault folder."""
    settings = settings or get_settings()
    if not settings.workspace.allow_edit:
        raise PathSecurityError("Editing is disabled.")
    root = _vault_root(settings)
    destination = (root / target_folder).resolve()
    if not destination.is_dir() or not is_in_vault(destination, settings):
        raise PathSecurityError(f"Import destination not allowed: {target_folder}")

    imported: list[dict] = []
    for raw in source_paths[:50]:
        src = Path(raw).expanduser().resolve()
        if not src.exists():
            continue
        if src == root:
            raise PathSecurityError("The vault root cannot be imported into itself.")
        try:
            destination.relative_to(src)
            raise PathSecurityError("A folder cannot be imported inside itself.")
        except ValueError:
            pass
        base_name = src.name
        dst = destination / base_name
        stem, suffix = dst.stem, dst.suffix
        counter = 2
        while dst.exists():
            dst = destination / f"{stem} {counter}{suffix}"
            counter += 1
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        imported.append(
            {
                "source": str(src),
                "path": dst.relative_to(root).as_posix(),
                "type": "folder" if dst.is_dir() else "file",
            }
        )
    return {"imported": imported, "count": len(imported)}


def copy_note(
    from_rel: str, to_rel: str, settings: Settings | None = None
) -> dict:
    """Duplicate a text note within the vault."""
    settings = settings or get_settings()
    root = _vault_root(settings)
    src = assert_workspace_readable(root / from_rel, settings)
    if not src.exists():
        raise FileNotFoundError(f"Note not found: {from_rel}")
    dst = assert_workspace_writable(root / to_rel, settings)
    if dst.exists():
        raise FileExistsError(f"Target already exists: {to_rel}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    new_rel = dst.relative_to(root).as_posix()
    return {"from": from_rel, "to": new_rel}


def merge_notes(
    target_rel: str,
    source_rel: str,
    delete_source: bool = False,
    settings: Settings | None = None,
) -> dict:
    """Append one text note to another, backing up the target first."""
    settings = settings or get_settings()
    root = _vault_root(settings)
    target = assert_workspace_writable(root / target_rel, settings)
    source = assert_workspace_readable(root / source_rel, settings)
    if not target.is_file() or not source.is_file():
        raise FileNotFoundError("Both merge paths must be files.")
    if target == source:
        raise ValueError("A note cannot be merged with itself.")
    target_text = target.read_text(encoding="utf-8", errors="replace")
    source_text = source.read_text(encoding="utf-8", errors="replace")
    separator = f"\n\n---\n\n## Merged from {source.stem}\n\n"
    result = write_note(target_rel, target_text.rstrip() + separator + source_text, settings)
    deleted = None
    if delete_source:
        deleted = delete_note(source_rel, settings)
    return {"target": target_rel, "source": source_rel, "deleted": deleted, **result}


def set_note_property(
    relpath: str, key: str, value: str, settings: Settings | None = None
) -> dict:
    """Add or replace one YAML frontmatter property."""
    settings = settings or get_settings()
    if not key.strip() or "\n" in key:
        raise ValueError("Property name is invalid.")
    root = _vault_root(settings)
    path = assert_workspace_writable(root / relpath, settings)
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        post = frontmatter.loads(raw)
        post.metadata[key.strip()] = value
        updated = frontmatter.dumps(post)
    except Exception:
        updated = f"---\n{key.strip()}: {json.dumps(value, ensure_ascii=False)}\n---\n\n{raw}"
    result = write_note(relpath, updated, settings)
    return {"path": relpath, "key": key.strip(), "value": value, **result}


def list_versions(relpath: str, settings: Settings | None = None) -> list[dict]:
    """List automatic backups for a note, newest first."""
    settings = settings or get_settings()
    root = _vault_root(settings)
    assert_workspace_readable(root / relpath, settings)
    backup_root = root / _BACKUP_DIR
    parent = backup_root / Path(relpath).parent
    pattern = f"{Path(relpath).name}.*.bak"
    versions: list[dict] = []
    if parent.exists():
        for path in sorted(parent.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
            versions.append(
                {
                    "id": path.relative_to(backup_root).as_posix(),
                    "timestamp": datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                    "size": path.stat().st_size,
                    "content": path.read_text(encoding="utf-8", errors="replace"),
                }
            )
    return versions


def restore_version(
    relpath: str, version_id: str, settings: Settings | None = None
) -> dict:
    """Restore one backup through write_note so the current version is preserved."""
    settings = settings or get_settings()
    root = _vault_root(settings)
    backup_root = (root / _BACKUP_DIR).resolve()
    version = (backup_root / version_id).resolve()
    try:
        version.relative_to(backup_root)
    except ValueError as exc:
        raise PathSecurityError("Version path is outside the backup area.") from exc
    if not version.is_file() or version.suffix.lower() != ".bak":
        raise FileNotFoundError("Version not found.")
    return write_note(
        relpath,
        version.read_text(encoding="utf-8", errors="replace"),
        settings,
    )


def delete_note(relpath: str, settings: Settings | None = None) -> dict:
    """Delete a note or folder reversibly into the vault backup area."""
    settings = settings or get_settings()
    root = _vault_root(settings)
    src = assert_workspace_readable(root / relpath, settings)
    if not src.exists():
        raise FileNotFoundError(f"Path not found: {relpath}")
    if src == root or src == settings.output_root.resolve():
        raise PathSecurityError("The vault root and StudyCopilot system folder cannot be deleted.")
    if src.is_file():
        src = assert_workspace_writable(src, settings)
    elif not settings.workspace.allow_edit or not is_in_vault(src, settings):
        raise PathSecurityError(f"Folder not editable: {relpath}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    dest = root / _BACKUP_DIR / "_deleted" / f"{relpath}.{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    logger.info("Deleted path %s (backup %s)", relpath, dest)
    return {"deleted": relpath, "backup": str(dest)}


def reveal_note(relpath: str, settings: Settings | None = None) -> dict:
    """Open the OS file explorer with the note selected (Windows)."""
    settings = settings or get_settings()
    p = assert_workspace_readable(_vault_root(settings) / relpath, settings)
    # explorer often returns a non-zero exit even on success; don't check it.
    subprocess.Popen(["explorer", f"/select,{p}"])
    return {"revealed": relpath}


def open_external(relpath: str, settings: Settings | None = None) -> dict:
    """Open an approved vault or indexed external source in its default app."""
    settings = settings or get_settings()
    supplied = Path(relpath).expanduser()
    p = (
        assert_readable(supplied, settings)
        if supplied.is_absolute()
        else assert_workspace_readable(_vault_root(settings) / supplied, settings)
    )
    if not p.exists():
        raise FileNotFoundError(f"Source not found: {relpath}")
    os.startfile(str(p))  # noqa: S606 - Windows desktop app, user-initiated
    return {"opened": str(p)}


_PDF_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.5; color: #111; }
h1 { font-size: 20pt; } h2 { font-size: 15pt; } h3 { font-size: 12pt; }
code { background: #f0f0f0; padding: 1px 3px; }
pre { background: #f5f5f5; padding: 8px; }
blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 10px; color: #555; }
table { border-collapse: collapse; } td, th { border: 1px solid #ccc; padding: 4px 8px; }
"""


def export_pdf(relpath: str, settings: Settings | None = None) -> dict:
    """Render the note's Markdown to a PDF under StudyCopilot/Exports/."""
    import fitz  # PyMuPDF
    import markdown as md

    settings = settings or get_settings()
    root = _vault_root(settings)
    p = assert_workspace_readable(root / relpath, settings)
    raw = p.read_text(encoding="utf-8", errors="replace")
    try:
        body = frontmatter.loads(raw).content
    except Exception:
        body = raw
    html_body = md.markdown(body, extensions=["extra", "sane_lists", "tables"])
    html = f"<html><head><style>{_PDF_CSS}</style></head><body><h1>{p.stem}</h1>{html_body}</body></html>"

    out = root / "StudyCopilot" / "Exports" / f"{p.stem}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)

    story = fitz.Story(html=html)
    writer = fitz.DocumentWriter(str(out))
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (50, 50, -50, -50)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    logger.info("Exported PDF %s -> %s", relpath, out)
    return {"pdf": str(out)}


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
