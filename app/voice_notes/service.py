"""High-level voice-note workflow."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config.settings import Settings
from app.generation.voice_notes import generate_voice_note_markdown
from app.obsidian.writer import safe_filename, write_note
from app.voice_notes.transcription import SUPPORTED_AUDIO_EXTENSIONS, transcribe_audio_file


@dataclass
class VoiceNoteResult:
    transcript: str
    markdown: str
    title: str
    model: str
    whisper_model_path: str
    written: bool
    target_path: str | None
    audio_path: str | None

    def as_dict(self) -> dict:
        return {
            "transcript": self.transcript,
            "markdown": self.markdown,
            "title": self.title,
            "model": self.model,
            "whisper_model_path": self.whisper_model_path,
            "written": self.written,
            "target_path": self.target_path,
            "audio_path": self.audio_path,
        }


@dataclass
class VoiceTranscriptionResult:
    transcript: str
    whisper_model_path: str
    audio_path: str | None

    def as_dict(self) -> dict:
        return {
            "transcript": self.transcript,
            "whisper_model_path": self.whisper_model_path,
            "audio_path": self.audio_path,
        }


def _slug_folder(value: str | None) -> str:
    if not value:
        return "Voice Notes"
    cleaned = re.sub(r'[<>:"\\|?*\x00-\x1f]', " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or "Voice Notes"


def _unique_target_path(settings: Settings, folder: str, title: str) -> str:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    name = safe_filename(f"{date_prefix} {title}")
    relative = Path("StudyCopilot") / folder / f"{name}.md"
    target = settings.vault.root / relative
    if not target.exists():
        return relative.as_posix()
    for index in range(2, 1000):
        candidate = Path("StudyCopilot") / folder / f"{name} {index}.md"
        if not (settings.vault.root / candidate).exists():
            return candidate.as_posix()
    raise FileExistsError(f"Could not create a unique voice note filename for {name}.")


def _with_transcript(markdown: str, transcript: str) -> str:
    return (
        f"{markdown.rstrip()}\n\n"
        "## Transcript\n\n"
        f"{transcript.strip()}\n"
    )


def prepare_audio_file(
    source_path: Path,
    *,
    original_name: str,
    settings: Settings,
) -> Path:
    extension = Path(original_name).suffix.lower() or source_path.suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise ValueError(f"Unsupported audio file type. Supported: {allowed}")
    audio_root = settings.voice_notes.audio_root
    audio_root.mkdir(parents=True, exist_ok=True)
    target = audio_root / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex}{extension}"
    shutil.copy2(source_path, target)
    return target


def create_voice_note_from_audio(
    audio_path: Path,
    *,
    settings: Settings,
    title: str | None = None,
    course: str | None = None,
    folder: str | None = None,
    write: bool = True,
) -> VoiceNoteResult:
    transcription = transcribe_voice_note_audio(audio_path, settings=settings)
    return create_voice_note_from_transcript(
        transcription.transcript,
        settings=settings,
        title=title,
        course=course,
        folder=folder,
        write=write,
        whisper_model_path=transcription.whisper_model_path,
        audio_path=transcription.audio_path,
    )


def transcribe_voice_note_audio(
    audio_path: Path,
    *,
    settings: Settings,
) -> VoiceTranscriptionResult:
    transcription = transcribe_audio_file(audio_path, settings)
    audio_result_path: str | None = str(audio_path) if settings.voice_notes.keep_audio else None
    if not settings.voice_notes.keep_audio:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass
    return VoiceTranscriptionResult(
        transcript=transcription.transcript,
        whisper_model_path=transcription.model_path,
        audio_path=audio_result_path,
    )


def create_voice_note_from_transcript(
    transcript: str,
    *,
    settings: Settings,
    title: str | None = None,
    course: str | None = None,
    folder: str | None = None,
    write: bool = True,
    whisper_model_path: str | None = None,
    audio_path: str | None = None,
) -> VoiceNoteResult:
    note = generate_voice_note_markdown(
        transcript,
        settings=settings,
        title=title,
        course=course,
    )
    markdown = _with_transcript(note.markdown, transcript)

    target_path: str | None = None
    written = False
    if write:
        target_path = _unique_target_path(settings, _slug_folder(folder), note.title)
        write_note(target_path, markdown, settings, overwrite=False)
        written = True

    return VoiceNoteResult(
        transcript=transcript,
        markdown=markdown,
        title=note.title,
        model=note.model,
        whisper_model_path=whisper_model_path or "",
        written=written,
        target_path=target_path,
        audio_path=audio_path,
    )
