"""AI-assisted, preview-first vault organization."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.generation.jsonparse import extract_json
from app.models.chat import ChatError, ChatMessage, get_chat_adapter
from app.security.paths import PathSecurityError, is_denied, is_in_vault

_SYSTEM = """You organize a personal notes vault.
Return STRICT JSON only: {"summary": str, "moves": [
  {"from": str, "to": str, "reason": str}
]}.
Rules:
- Paths are vault-relative and use forward slashes.
- Only move existing files or folders. Never rename: the final basename in
  "to" must exactly equal the final basename in "from".
- Never delete, merge, overwrite, or move anything into hidden/system folders.
- Do not move StudyCopilot.
- Prefer a small, understandable set of high-confidence moves.
- Do not propose moving both a folder and anything inside that folder.
"""


def _root(settings: Settings) -> Path:
    return Path(settings.vault.root).expanduser().resolve()


def _inventory(settings: Settings, limit: int = 1200) -> list[dict]:
    root = _root(settings)
    items: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        dirnames[:] = [
            name
            for name in dirnames
            if not name.startswith(".")
            and name != "StudyCopilot"
            and not is_denied(base / name, settings)
        ]
        for name in dirnames:
            path = base / name
            items.append({"path": path.relative_to(root).as_posix(), "type": "folder"})
        for name in filenames:
            path = base / name
            if not name.startswith(".") and not is_denied(path, settings):
                items.append({"path": path.relative_to(root).as_posix(), "type": "file"})
        if len(items) >= limit:
            break
    return items[:limit]


def _validate_moves(raw_moves: list, settings: Settings) -> list[dict]:
    root = _root(settings)
    validated: list[dict] = []
    sources: list[Path] = []
    destinations: set[Path] = set()

    for raw in raw_moves[:80]:
        if not isinstance(raw, dict):
            continue
        from_rel = str(raw.get("from", "")).replace("\\", "/").strip("/")
        to_rel = str(raw.get("to", "")).replace("\\", "/").strip("/")
        if not from_rel or not to_rel or from_rel == to_rel:
            continue
        src = (root / from_rel).resolve()
        dst = (root / to_rel).resolve()
        if (
            not src.exists()
            or not is_in_vault(src, settings)
            or not is_in_vault(dst, settings)
            or is_denied(src, settings)
            or is_denied(dst, settings)
            or "StudyCopilot" in src.relative_to(root).parts
            or "StudyCopilot" in dst.relative_to(root).parts
            or src.name != dst.name
            or dst.exists()
            or dst in destinations
        ):
            continue
        try:
            dst.relative_to(src)
            continue
        except ValueError:
            pass
        sources.append(src)
        destinations.add(dst)
        validated.append(
            {
                "from": src.relative_to(root).as_posix(),
                "to": dst.relative_to(root).as_posix(),
                "reason": str(raw.get("reason", "")).strip(),
            }
        )

    # Reject ambiguous plans that move a folder and one of its descendants.
    for index, source in enumerate(sources):
        for other in sources[index + 1 :]:
            if source in other.parents or other in source.parents:
                raise PathSecurityError(
                    "Organizer proposed overlapping moves. Generate a new preview."
                )
    return validated


def preview_organization(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    inventory = _inventory(settings)
    adapter = get_chat_adapter(settings)
    prompt = (
        "Here is the current vault inventory. Suggest a cleaner structure while "
        "preserving every item's exact name.\n\n"
        + json.dumps(inventory, ensure_ascii=False)
    )
    try:
        response = adapter.generate(
            [
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.1,
        )
        data = extract_json(response.content)
    except (ChatError, ValueError) as exc:
        raise RuntimeError(f"AI organizer could not create a preview: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError("AI organizer returned an invalid plan.")
    moves = _validate_moves(data.get("moves", []), settings)
    return {
        "summary": str(data.get("summary", "")).strip(),
        "moves": moves,
        "inventory_count": len(inventory),
        "model": adapter.model_name,
    }


def apply_organization(moves: list[dict], settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    validated = _validate_moves(moves, settings)
    if not validated:
        return {"applied": 0, "moves": []}

    root = _root(settings)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    manifest = root / "StudyCopilot" / "_backups" / "organizer" / f"{stamp}.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps({"moves": validated}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    applied: list[dict] = []
    for move in validated:
        src = root / move["from"]
        dst = root / move["to"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        applied.append(move)
    return {"applied": len(applied), "moves": applied, "manifest": str(manifest)}
