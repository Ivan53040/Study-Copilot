"""Ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.ingestion.service import ingest, ingest_single_file
from app.security.paths import PathSecurityError

router = APIRouter(prefix="/ingest", tags=["ingest"])


class ScanRequest(BaseModel):
    course: str | None = None


class FileRequest(BaseModel):
    path: str


@router.post("/scan")
def scan(req: ScanRequest, settings: Settings = Depends(get_settings)) -> dict:
    report = ingest(settings=settings, course=req.course)
    return report.as_dict()


@router.post("/file")
def file(req: FileRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        report = ingest_single_file(req.path, settings=settings)
    except PathSecurityError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return report.as_dict()
