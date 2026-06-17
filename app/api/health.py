"""Health and config-sanity endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.config.settings import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    vault_root = settings.vault.root
    return {
        "status": "ok",
        "version": __version__,
        "vault_root": str(vault_root),
        "vault_exists": vault_root.exists(),
        "output_root": str(settings.output_root),
        "default_provider": settings.models.default_provider,
        "external_sources": len(settings.external_sources),
    }
