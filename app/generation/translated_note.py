"""Generate translated sibling notes inside the workspace vault."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from app.config.settings import Settings
from app.generation.translation import (
    MAX_BATCH_CHARS,
    MAX_BATCH_ITEMS,
    translate_batch_english_to_traditional_chinese,
    translate_english_to_traditional_chinese,
)
from app.models.chat import ChatError
from app.vault.service import read_note, write_note

_FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _clean_markdown_text(markdown: str) -> str:
    return (
        markdown.replace("`", "")
        .replace("*", "")
        .replace("_", "")
        .replace("~", "")
        .strip()
    )


def _markdown_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    for raw in re.split(r"\n{2,}", markdown):
        block = raw.strip()
        if not block:
            continue
        if block.startswith("```") or block.startswith("~~~"):
            blocks.append({"kind": "skip", "markdown": block, "text": ""})
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", block)
        if heading:
            text = _clean_markdown_text(heading.group(2))
            blocks.append(
                {
                    "kind": "heading",
                    "markdown": block,
                    "prefix": heading.group(1),
                    "text": text,
                }
            )
            continue
        text = _clean_markdown_text(block)
        blocks.append({"kind": "text", "markdown": block, "text": text})
    return blocks


def _has_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text))


def _translation_chunks(blocks: list[dict], max_chars: int = 3500) -> list[dict]:
    chunks: list[dict] = []
    pending: list[str] = []
    pending_chars = 0

    def flush() -> None:
        nonlocal pending, pending_chars
        if pending:
            chunks.append({"kind": "translate", "markdown": "\n\n".join(pending)})
            pending = []
            pending_chars = 0

    for block in blocks:
        markdown = block["markdown"]
        if block["kind"] == "skip" or not _has_english(block["text"]):
            flush()
            chunks.append({"kind": "keep", "markdown": markdown})
            continue
        extra = len(markdown) + (2 if pending else 0)
        if pending and pending_chars + extra > max_chars:
            flush()
        if len(markdown) > max_chars:
            chunks.append({"kind": "translate", "markdown": markdown})
        else:
            pending.append(markdown)
            pending_chars += extra
    flush()
    return chunks


def _target_path(source_path: str, settings: Settings) -> str:
    source = Path(source_path)
    parent = source.parent
    suffix = source.suffix or ".md"
    stem = source.stem
    root = Path(settings.vault.root).expanduser().resolve()
    candidate = parent / f"{stem}(translated){suffix}"
    counter = 2
    while (root / candidate).exists():
        candidate = parent / f"{stem}(translated {counter}){suffix}"
        counter += 1
    return candidate.as_posix()


def _translate_markdown_chunks(chunks: list[dict], settings: Settings) -> list[str]:
    translated: dict[int, str] = {}
    batch: list[tuple[int, str]] = []
    batch_chars = 0

    def translate_one(text: str) -> str:
        for _ in range(2):
            try:
                return translate_english_to_traditional_chinese(
                    text,
                    settings=settings,
                ).translation
            except ChatError:
                continue
        return (
            "<!-- Study Copilot: this section could not be translated by the "
            "local model, so the original text was preserved. -->\n\n"
            f"{text}"
        )

    def translate_batch(texts: list[str]) -> list[str]:
        if len(texts) == 1:
            return [translate_one(texts[0])]
        try:
            result = translate_batch_english_to_traditional_chinese(
                texts,
                settings=settings,
            )
            return result.translations
        except (ChatError, ValueError):
            midpoint = max(1, len(texts) // 2)
            return translate_batch(texts[:midpoint]) + translate_batch(texts[midpoint:])

    def flush() -> None:
        nonlocal batch, batch_chars
        if not batch:
            return
        texts = [text for _, text in batch]
        for (index, _), translation in zip(batch, translate_batch(texts)):
            translated[index] = translation
        batch = []
        batch_chars = 0

    for index, chunk in enumerate(chunks):
        if chunk["kind"] == "keep":
            continue
        text = chunk["markdown"]
        extra = len(text)
        if batch and (
            len(batch) >= MAX_BATCH_ITEMS
            or batch_chars + extra > MAX_BATCH_CHARS
        ):
            flush()
        batch.append((index, text))
        batch_chars += extra
    flush()

    output: list[str] = []
    for index, chunk in enumerate(chunks):
        output.append(chunk["markdown"] if chunk["kind"] == "keep" else translated[index])
    return output


def _placeholder_content(source_stem: str, status: str, error: str | None = None) -> str:
    frontmatter = (
        "---\n"
        f'translated_from: "[[{source_stem}]]"\n'
        'source_language: "English"\n'
        'target_language: "Traditional Chinese"\n'
        f'translated_status: "{status}"\n'
        "---\n\n"
    )
    if status == "failed":
        return frontmatter + (
            f"# {source_stem}(translated)\n\n"
            "Study Copilot could not finish translating this note.\n\n"
            f"Error: {error or 'Unknown error'}\n"
        )
    return frontmatter + (
        f"# {source_stem}(translated)\n\n"
        "Study Copilot is translating this note in the background. "
        "Reopen or refresh this note in a moment to see the Chinese version.\n"
    )


def _translated_content(path: str, settings: Settings) -> tuple[str, int]:
    note = read_note(path, settings)
    body = _strip_frontmatter(note["content"])
    blocks = _markdown_blocks(body)
    chunks = _translation_chunks(blocks)
    translatable_count = sum(1 for chunk in chunks if chunk["kind"] == "translate")
    if translatable_count == 0:
        raise ValueError("No English text found to translate.")

    translated_chunks = _translate_markdown_chunks(chunks, settings)

    source_stem = Path(path).stem
    try:
        title = translate_english_to_traditional_chinese(
            source_stem,
            settings=settings,
        ).translation
    except ChatError:
        title = source_stem
    content = (
        "---\n"
        f'translated_from: "[[{source_stem}]]"\n'
        'source_language: "English"\n'
        'target_language: "Traditional Chinese"\n'
        'translated_status: "succeeded"\n'
        "---\n\n"
        f"# {title}\n\n"
        + "\n\n".join(translated_chunks).lstrip()
        + "\n"
    )
    return content, translatable_count


def translate_note_to_sibling(path: str, settings: Settings) -> dict:
    target = _target_path(path, settings)
    content, translatable_count = _translated_content(path, settings)
    write_note(target, content, settings)
    return {
        "source_path": path,
        "path": target,
        "title": Path(target).stem,
        "blocks": translatable_count,
        "written": True,
        "status": "succeeded",
    }


def translate_note_to_sibling_background(path: str, settings: Settings) -> dict:
    # Validate and choose the final path before returning to the UI.
    read_note(path, settings)
    target = _target_path(path, settings)
    source_stem = Path(path).stem
    write_note(target, _placeholder_content(source_stem, "running"), settings)

    def worker() -> None:
        try:
            content, _ = _translated_content(path, settings)
        except Exception as exc:  # keep the visible note useful after failures
            write_note(target, _placeholder_content(source_stem, "failed", str(exc)), settings)
            return
        write_note(target, content, settings)

    threading.Thread(target=worker, daemon=True).start()
    return {
        "source_path": path,
        "path": target,
        "title": Path(target).stem,
        "blocks": 0,
        "written": True,
        "status": "running",
    }
