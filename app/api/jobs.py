"""Background job endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import Settings, get_settings
from app.jobs.service import cancel_job, get_job, list_jobs, submit_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobRequest(BaseModel):
    type: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


@router.post("")
def create_job(req: JobRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return submit_job(req.type, req.payload, settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def get_jobs(settings: Settings = Depends(get_settings)) -> dict:
    return {"jobs": list_jobs(settings)}


@router.get("/{job_id}")
def read_job(job_id: int, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return get_job(job_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/cancel")
def cancel(job_id: int, settings: Settings = Depends(get_settings)) -> dict:
    try:
        return cancel_job(job_id, settings)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
