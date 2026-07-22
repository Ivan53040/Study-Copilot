"""Revision-note generation endpoint (preview by default; write to StudyCopilot/)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.config.settings import Settings, get_settings
from app.generation.translation import (
    MAX_BATCH_CHARS,
    MAX_BATCH_ITEMS,
    translate_batch_english_to_traditional_chinese,
    translate_english_to_traditional_chinese,
)
from app.generation.translated_note import (
    translate_note_to_sibling,
    translate_note_to_sibling_background,
)
from app.generation.revision_notes import generate_revision_note
from app.models.chat import ChatError
from app.security.paths import PathSecurityError

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteRequest(BaseModel):
    course: str | None = None
    scope_path: str | None = None
    scope_name: str | None = None
    study_set_id: int | None = None
    week: int | None = None
    topic: str | None = None
    # Preview by default; set write=true to save into StudyCopilot/.
    write: bool = False
    overwrite: bool = True

    @model_validator(mode="after")
    def _need_a_scope(self):
        if not (self.course or self.scope_path or self.study_set_id or self.topic):
            raise ValueError("Provide at least a vault scope or a topic.")
        return self


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    context: str | None = None


class TranslateBatchRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)


class TranslateNoteRequest(BaseModel):
    path: str = Field(min_length=1)
    background: bool = False


@router.post("/generate")
def post_generate(
    req: NoteRequest, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        preview = generate_revision_note(
            course=req.course,
            scope_path=req.scope_path,
            scope_name=req.scope_name,
            study_set_id=req.study_set_id,
            week=req.week,
            topic=req.topic,
            settings=settings,
            write=req.write,
            overwrite=req.overwrite,
        )
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return preview.as_dict()


@router.post("/translate")
def post_translate(
    req: TranslateRequest, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return translate_english_to_traditional_chinese(
            req.text,
            context=req.context,
            settings=settings,
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Local LLM translation failed. Make sure LM Studio is running "
                f"and the configured model is loaded. {exc}"
            ),
        ) from exc


@router.post("/translate-batch")
def post_translate_batch(
    req: TranslateBatchRequest, settings: Settings = Depends(get_settings)
) -> dict:
    if sum(len(text) for text in req.texts) > MAX_BATCH_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Batch translation is too long; maximum is {MAX_BATCH_CHARS} characters.",
        )
    try:
        return translate_batch_english_to_traditional_chinese(
            req.texts,
            settings=settings,
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Local LLM translation failed. Make sure LM Studio is running "
                f"and the configured model is loaded. {exc}"
            ),
        ) from exc


@router.post("/translate-note")
def post_translate_note(
    req: TranslateNoteRequest, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        if req.background:
            return translate_note_to_sibling_background(req.path, settings)
        return translate_note_to_sibling(req.path, settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Local LLM translation failed. Make sure LM Studio is running "
                f"and the configured model is loaded. {exc}"
            ),
        ) from exc
