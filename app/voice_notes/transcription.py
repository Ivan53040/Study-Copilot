"""Local audio transcription through whisper.cpp."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.config.settings import Settings

SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}


class VoiceNoteError(RuntimeError):
    pass


@dataclass
class TranscriptionResult:
    transcript: str
    model_path: str
    audio_path: str | None = None


def _ensure_executable(command: str, label: str) -> str:
    candidate = Path(command)
    if candidate.exists():
        return str(candidate)
    found = shutil.which(command)
    if found:
        return found
    raise VoiceNoteError(
        f"{label} was not found. Configure its path in voice_notes or add it to PATH."
    )


def _ensure_model(settings: Settings) -> Path:
    model = settings.voice_notes.whisper_model_path
    if model is None:
        raise VoiceNoteError("voice_notes.whisper_model_path is not configured.")
    if model.suffix.lower() == ".part":
        raise VoiceNoteError(
            f"Whisper model is still downloading: {model}. Wait for the final .gguf file."
        )
    if not model.exists() or model.stat().st_size == 0:
        raise VoiceNoteError(f"Whisper model file is missing or empty: {model}")
    return model


def _convert_to_wav(source: Path, target: Path, settings: Settings) -> None:
    ffmpeg = _ensure_executable(settings.voice_notes.ffmpeg_path, "ffmpeg")
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(target),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise VoiceNoteError(f"Audio conversion failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VoiceNoteError("Audio conversion timed out.") from exc
    if completed.stderr:
        # ffmpeg writes normal progress to stderr; keep this branch only for debugging.
        pass


def _run_whisper(wav_path: Path, settings: Settings) -> str:
    whisper = _ensure_executable(settings.voice_notes.whisper_cli_path, "whisper-cli")
    model = _ensure_model(settings)
    out_base = wav_path.with_suffix("")
    cmd = [
        whisper,
        "-m",
        str(model),
        "-f",
        str(wav_path),
        "-otxt",
        "-of",
        str(out_base),
        "-nt",
    ]
    language = settings.voice_notes.language.strip()
    if language and language.lower() != "auto":
        cmd.extend(["-l", language])

    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise VoiceNoteError(f"Whisper transcription failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VoiceNoteError("Whisper transcription timed out.") from exc

    txt_path = out_base.with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8", errors="replace").strip()
    return (completed.stdout or "").strip()


def transcribe_audio_file(audio_path: Path, settings: Settings) -> TranscriptionResult:
    """Convert an uploaded audio file to wav and transcribe it locally."""
    if not settings.voice_notes.enabled:
        raise VoiceNoteError("Voice notes are disabled in config.")
    if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise VoiceNoteError(f"Unsupported audio file type. Supported: {allowed}")

    with TemporaryDirectory(prefix="study-copilot-voice-") as tmp:
        wav_path = Path(tmp) / "audio.wav"
        _convert_to_wav(audio_path, wav_path, settings)
        transcript = _run_whisper(wav_path, settings)

    if not transcript:
        raise VoiceNoteError("Whisper returned an empty transcript.")
    model = _ensure_model(settings)
    return TranscriptionResult(
        transcript=transcript,
        model_path=str(model),
        audio_path=str(audio_path) if settings.voice_notes.keep_audio else None,
    )
