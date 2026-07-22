"""Voice-note endpoints."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.models.chat import ChatError
from app.security.paths import PathSecurityError
from app.voice_notes.service import (
    create_voice_note_from_audio,
    create_voice_note_from_transcript,
    transcribe_voice_note_audio,
)
from app.voice_notes.transcription import SUPPORTED_AUDIO_EXTENSIONS, VoiceNoteError

router = APIRouter(prefix="/voice-notes", tags=["voice-notes"])


class GenerateFromTranscriptRequest(BaseModel):
    transcript: str = Field(min_length=1)
    title: str | None = None
    course: str | None = None
    folder: str | None = "Voice Notes"
    write: bool = True


def _configured_executable(command: str) -> bool:
    candidate = Path(command)
    return candidate.exists() or shutil.which(command) is not None


@router.get("/status")
def get_voice_note_status(settings: Settings = Depends(get_settings)) -> dict:
    model = settings.voice_notes.whisper_model_path
    return {
        "enabled": settings.voice_notes.enabled,
        "model_path": str(model) if model else None,
        "model_exists": bool(model and model.exists() and model.stat().st_size > 0),
        "model_is_partial": bool(model and model.suffix.lower() == ".part"),
        "whisper_cli_path": settings.voice_notes.whisper_cli_path,
        "whisper_cli_available": _configured_executable(settings.voice_notes.whisper_cli_path),
        "ffmpeg_path": settings.voice_notes.ffmpeg_path,
        "ffmpeg_available": _configured_executable(settings.voice_notes.ffmpeg_path),
        "language": settings.voice_notes.language,
        "max_upload_mb": settings.voice_notes.max_upload_mb,
    }


async def _save_upload(upload: UploadFile, settings: Settings) -> Path:
    original = upload.filename or "voice-note.webm"
    suffix = Path(original).suffix.lower()
    if suffix not in SUPPORTED_AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio file type. Supported: {allowed}",
        )

    max_bytes = settings.voice_notes.max_upload_mb * 1024 * 1024
    audio_root = settings.voice_notes.audio_root
    audio_root.mkdir(parents=True, exist_ok=True)
    path = audio_root / (
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex}{suffix}"
    )

    size = 0
    try:
        with path.open("wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Audio upload exceeds {settings.voice_notes.max_upload_mb} MB.",
                    )
                handle.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if size == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded audio file is empty.")
    return path


@router.post("")
async def post_voice_note(
    audio: UploadFile = File(...),
    title: str | None = Form(default=None),
    course: str | None = Form(default=None),
    folder: str | None = Form(default="Voice Notes"),
    write: bool = Form(default=True),
    settings: Settings = Depends(get_settings),
) -> dict:
    saved_path: Path | None = None
    try:
        saved_path = await _save_upload(audio, settings)
        result = create_voice_note_from_audio(
            saved_path,
            settings=settings,
            title=title,
            course=course,
            folder=folder,
            write=write,
        )
        return result.as_dict()
    except HTTPException:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise
    except VoiceNoteError as exc:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatError as exc:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=502,
            detail=(
                "Local LLM voice-note generation failed. Make sure LM Studio is "
                f"running and the configured model is loaded. {exc}"
            ),
        ) from exc
    except PathSecurityError as exc:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transcribe")
async def post_transcribe_voice_note(
    audio: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> dict:
    saved_path: Path | None = None
    try:
        saved_path = await _save_upload(audio, settings)
        return transcribe_voice_note_audio(saved_path, settings=settings).as_dict()
    except HTTPException:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise
    except VoiceNoteError as exc:
        if saved_path is not None and not settings.voice_notes.keep_audio:
            saved_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate")
def post_generate_voice_note_from_transcript(
    req: GenerateFromTranscriptRequest,
    settings: Settings = Depends(get_settings),
) -> dict:
    try:
        result = create_voice_note_from_transcript(
            req.transcript,
            settings=settings,
            title=req.title,
            course=req.course,
            folder=req.folder,
            write=req.write,
        )
        return result.as_dict()
    except ChatError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Local LLM voice-note generation failed. Make sure LM Studio is "
                f"running and the configured model is loaded. {exc}"
            ),
        ) from exc
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
