"""Reusable transformation endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.transformations.service import (
    delete_template,
    list_templates,
    save_template,
    submit_transformation,
)

router = APIRouter(prefix="/transformations", tags=["transformations"])


class TemplatePayload(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    prompt: str = Field(min_length=1)
    apply_default: bool = False


class RunPayload(BaseModel):
    template_id: int
    target_kind: str
    target_ref: str | None = None
    study_set_id: int | None = None


@router.get("/templates")
def templates(settings: Settings = Depends(get_settings)) -> dict:
    return {"templates": list_templates(settings)}


@router.post("/templates")
def create_template(
    req: TemplatePayload, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return save_template(settings=settings, **req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/templates/{template_id}")
def update_template(
    template_id: int, req: TemplatePayload, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return save_template(settings=settings, template_id=template_id, **req.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/templates/{template_id}")
def remove_template(template_id: int, settings: Settings = Depends(get_settings)) -> dict:
    try:
        delete_template(template_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": template_id}


@router.post("/run")
def run(req: RunPayload, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return submit_transformation(settings=settings, **req.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
