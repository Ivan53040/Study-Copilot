"""Deep Ask endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.deep_ask.service import submit_deep_ask

router = APIRouter(prefix="/ask", tags=["ask"])


class DeepAskRequest(BaseModel):
    question: str = Field(min_length=1)
    course: str | None = None
    scope_path: str | None = None
    study_set_id: int | None = None
    max_searches: int = 4


@router.post("/deep")
def deep_ask(req: DeepAskRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return submit_deep_ask(settings=settings, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
