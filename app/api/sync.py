"""Sync status + manual-trigger endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config.settings import Settings, get_settings
from app.sync.icloud_sync import SyncError
from app.sync.service import run_sync

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
def status(request: Request) -> dict:
    scheduler = getattr(request.app.state, "sync_scheduler", None)
    if scheduler is None:
        return {"enabled": False, "running": False}
    return {"enabled": True, **scheduler.status()}


@router.post("/run")
def run(
    dry_run: bool = False, settings: Settings = Depends(get_settings)
) -> dict:
    try:
        result = run_sync(settings, dry_run=dry_run)
    except SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.as_dict()
