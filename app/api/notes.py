"""Revision-note generation endpoint (preview by default; write to StudyCopilot/)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator

from app.config.settings import Settings, get_settings
from app.generation.revision_notes import generate_revision_note
from app.security.paths import PathSecurityError

router = APIRouter(prefix="/notes", tags=["notes"])


class NoteRequest(BaseModel):
    course: str | None = None
    week: int | None = None
    topic: str | None = None
    # Preview by default; set write=true to save into StudyCopilot/.
    write: bool = False
    overwrite: bool = True

    @model_validator(mode="after")
    def _need_a_scope(self):
        if not (self.course or self.topic):
            raise ValueError("Provide at least a course or a topic.")
        return self


@router.post("/generate")
def post_generate(
    req: NoteRequest, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        preview = generate_revision_note(
            course=req.course,
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
