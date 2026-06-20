"""Preview-first AI Markdown formatting for one vault note."""

from __future__ import annotations

import re
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.models.chat import ChatAdapter, ChatError, ChatMessage, get_chat_adapter
from app.security.paths import assert_workspace_readable

_SYSTEM = """You format Markdown notes without changing their meaning.
Return only the complete formatted Markdown body, with no commentary and no
surrounding code fence.

Rules:
- Preserve every fact, sentence, citation, URL, wikilink, embed, code block,
  equation, task state, and data value.
- Do not summarize, translate, invent, remove, or rewrite substantive content.
- Improve only Markdown structure: headings, spacing, lists, tables, callouts,
  emphasis, and readable grouping.
- Keep the original language.
- Do not add YAML frontmatter; it is handled separately.
"""

_FENCE_RE = re.compile(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", re.S | re.I)


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---"):
        return "", raw
    match = re.match(r"^(---\r?\n.*?\r?\n---\r?\n)(.*)$", raw, re.S)
    if not match:
        return "", raw
    return match.group(1), match.group(2)


def _clean_response(content: str) -> str:
    cleaned = content.strip()
    fenced = _FENCE_RE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    return cleaned


def preview_document_format(
    relpath: str,
    content: str | None = None,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
) -> dict:
    settings = settings or get_settings()
    root = Path(settings.vault.root).expanduser().resolve()
    path = assert_workspace_readable(root / relpath, settings)
    raw = content if content is not None else path.read_text(
        encoding="utf-8", errors="replace"
    )
    frontmatter, body = _split_frontmatter(raw)
    if not body.strip():
        raise ValueError("The note has no content to format.")

    adapter = adapter or get_chat_adapter(settings)
    if adapter.model_name == "echo":
        raise RuntimeError(
            "AI formatting requires an active LLM. Configure LM Studio in Settings."
        )
    try:
        response = adapter.generate(
            [
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(
                    role="user",
                    content=(
                        "Format this Markdown document while obeying every rule:\n\n"
                        + body
                    ),
                ),
            ],
            temperature=0.05,
            max_tokens=max(1200, min(12000, len(body) * 2)),
        )
    except ChatError as exc:
        raise RuntimeError(f"AI formatter could not reach the model: {exc}") from exc

    formatted_body = _clean_response(response.content)
    if not formatted_body:
        raise RuntimeError("AI formatter returned an empty document.")

    suffix = "\n" if raw.endswith("\n") else ""
    formatted = frontmatter + formatted_body.rstrip() + suffix
    return {
        "path": relpath,
        "before": raw,
        "after": formatted,
        "changed": formatted != raw,
        "model": response.model,
    }
