"""Study set endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.study_sets.service import (
    delete_study_set,
    get_study_set,
    list_study_sets,
    save_study_set,
)

router = APIRouter(prefix="/study-sets", tags=["study-sets"])


class StudySetItemPayload(BaseModel):
    kind: str
    ref: str | int
    mode: str = "snippets"


class StudySetPayload(BaseModel):
    name: str = Field(min_length=1)
    course: str | None = None
    scope_path: str | None = None
    items: list[StudySetItemPayload] = Field(default_factory=list)


@router.get("")
def list_sets(settings: Settings = Depends(get_settings)) -> dict:
    return {"study_sets": list_study_sets(settings)}


@router.get("/{study_set_id}")
def get_set(study_set_id: int, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return get_study_set(study_set_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("")
def create_set(req: StudySetPayload, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return save_study_set(
            settings=settings,
            name=req.name,
            course=req.course,
            scope_path=req.scope_path,
            items=[item.model_dump() for item in req.items],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{study_set_id}")
def update_set(
    study_set_id: int, req: StudySetPayload, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        return save_study_set(
            settings=settings,
            study_set_id=study_set_id,
            name=req.name,
            course=req.course,
            scope_path=req.scope_path,
            items=[item.model_dump() for item in req.items],
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{study_set_id}")
def delete_set(study_set_id: int, settings: Settings = Depends(get_settings)) -> dict:
    try:
        delete_study_set(study_set_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": study_set_id}
