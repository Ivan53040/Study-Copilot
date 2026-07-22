"""Generate study-note Markdown from voice transcripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from app.config.settings import Settings
from app.models.chat import ChatMessage, get_chat_adapter

MAX_TRANSCRIPT_CHARS = 24000
CHUNK_CHARS = 12000


@dataclass
class VoiceNoteMarkdown:
    title: str
    markdown: str
    model: str


def _split_text(text: str, limit: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [text]:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= limit:
            current = paragraph
        else:
            chunks.extend(paragraph[i : i + limit] for i in range(0, len(paragraph), limit))
            current = ""
    if current:
        chunks.append(current)
    return chunks


def _extract_title(markdown: str, fallback: str | None = None) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()[:120]
    return fallback or f"Voice Note {datetime.now().strftime('%Y-%m-%d %H-%M')}"


def _generate_for_transcript(
    transcript: str,
    *,
    settings: Settings,
    title: str | None = None,
    course: str | None = None,
) -> VoiceNoteMarkdown:
    adapter = get_chat_adapter(settings, task="voice_notes", timeout=300.0)
    course_line = f"Course/context: {course}" if course else "Course/context: not specified"
    title_line = f"Suggested title: {title}" if title else "Suggested title: infer one"
    messages = [
        ChatMessage(
            role="system",
            content=(
                "You turn raw spoken transcripts into clear, useful study notes. "
                "Keep only content supported by the transcript. If a section has no "
                "useful material, omit it."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                f"{course_line}\n{title_line}\n\n"
                "Create Markdown study notes with this structure:\n"
                "# Title\n"
                "## Summary\n"
                "## Key Points\n"
                "## Definitions\n"
                "## Questions To Review\n"
                "## Flashcards\n\n"
                "Use concise bullets. Preserve important names, numbers, formulas, "
                "and uncertainty from the transcript.\n\n"
                f"Transcript:\n{transcript}"
            ),
        ),
    ]
    response = adapter.generate(messages, temperature=settings.generation.temperature)
    markdown = response.content.strip()
    return VoiceNoteMarkdown(
        title=_extract_title(markdown, title),
        markdown=markdown,
        model=response.model,
    )


def generate_voice_note_markdown(
    transcript: str,
    *,
    settings: Settings,
    title: str | None = None,
    course: str | None = None,
) -> VoiceNoteMarkdown:
    cleaned = transcript.strip()
    if not cleaned:
        raise ValueError("Transcript is empty.")
    if len(cleaned) <= MAX_TRANSCRIPT_CHARS:
        return _generate_for_transcript(
            cleaned,
            settings=settings,
            title=title,
            course=course,
        )

    adapter = get_chat_adapter(settings, task="voice_notes", timeout=300.0)
    chunk_notes: list[str] = []
    for index, chunk in enumerate(_split_text(cleaned, CHUNK_CHARS), start=1):
        response = adapter.generate(
            [
                ChatMessage(
                    role="system",
                    content=(
                        "Summarize this transcript chunk into compact study-note bullets. "
                        "Keep facts, terms, examples, formulas, and open questions."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=f"Chunk {index}:\n{chunk}",
                ),
            ],
            temperature=settings.generation.temperature,
        )
        chunk_notes.append(f"## Chunk {index}\n\n{response.content.strip()}")

    combined = "\n\n".join(chunk_notes)
    return _generate_for_transcript(
        combined,
        settings=settings,
        title=title,
        course=course,
    )
