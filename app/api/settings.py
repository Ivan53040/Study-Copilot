"""Runtime-editable application settings."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config.settings import get_settings, load_settings

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    vault_root: str = Field(min_length=1)
    lectures_root: str | None = None
    default_provider: str = "lmstudio"
    llm_base_url: str = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    embedding_provider: str = "lmstudio"
    embedding_base_url: str | None = None
    embedding_model: str = Field(min_length=1)
    temperature: float = Field(ge=0, le=2)
    require_citations: bool = True


class ConnectionTest(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)


def _config_path() -> Path:
    return Path(os.environ.get("STUDY_COPILOT_CONFIG", "config.yaml")).resolve()


def _public_settings() -> dict:
    settings = get_settings()
    lectures_root = settings.lectures.root
    return {
        "vault_root": str(settings.vault.root),
        "vault_exists": settings.vault.root.is_dir(),
        "lectures_root": str(lectures_root) if lectures_root else None,
        "lectures_root_exists": lectures_root.is_dir() if lectures_root else None,
        "default_provider": settings.models.default_provider,
        "llm_base_url": settings.models.lmstudio.base_url,
        "llm_model": settings.models.lmstudio.model,
        "embedding_provider": settings.embeddings.provider,
        "embedding_base_url": settings.embeddings.base_url,
        "embedding_model": settings.embeddings.model,
        "temperature": settings.generation.temperature,
        "require_citations": settings.generation.require_citations,
    }


@router.get("")
def read_settings() -> dict:
    return _public_settings()


@router.put("")
def update_settings(req: SettingsUpdate) -> dict:
    config_path = _config_path()
    vault_root = Path(os.path.expanduser(req.vault_root)).resolve()
    if not vault_root.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Vault folder does not exist: {vault_root}"
        )
    if req.default_provider not in {"lmstudio", "echo"}:
        raise HTTPException(status_code=400, detail="Unsupported chat provider")
    if req.embedding_provider not in {"lmstudio", "hash"}:
        raise HTTPException(status_code=400, detail="Unsupported embedding provider")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    data.setdefault("vault", {})["root"] = str(vault_root)

    if req.lectures_root:
        lectures_root = Path(os.path.expanduser(req.lectures_root)).resolve()
        if not lectures_root.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Lecture notes folder does not exist: {lectures_root}",
            )
        data.setdefault("lectures", {})["root"] = str(lectures_root)
    else:
        data.pop("lectures", None)
    # A selected vault is the user's approved study workspace. Index all
    # non-denied content so every course can power Library, plans and exams.
    data["vault"]["read_paths"] = ["**"]
    models = data.setdefault("models", {})
    models["default_provider"] = req.default_provider
    lmstudio = models.setdefault("lmstudio", {})
    lmstudio["base_url"] = req.llm_base_url.rstrip("/")
    lmstudio["model"] = req.llm_model

    embeddings = data.setdefault("embeddings", {})
    embeddings["provider"] = req.embedding_provider
    embeddings["model"] = req.embedding_model
    embeddings["base_url"] = (
        req.embedding_base_url.rstrip("/") if req.embedding_base_url else None
    )

    generation = data.setdefault("generation", {})
    generation["temperature"] = req.temperature
    generation["require_citations"] = req.require_citations

    # Validate the complete config before replacing the live file.
    load_settings_data = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=config_path.parent, delete=False, suffix=".yaml"
    ) as temp:
        temp.write(load_settings_data)
        temp_path = Path(temp.name)
    try:
        load_settings(temp_path)
        os.replace(temp_path, config_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    get_settings.cache_clear()
    return {"saved": True, "settings": _public_settings()}


@router.post("/test-llm")
def test_llm(req: ConnectionTest) -> dict:
    base_url = req.base_url.rstrip("/")
    try:
        response = httpx.get(f"{base_url}/models", timeout=8)
        response.raise_for_status()
        payload = response.json()
        model_ids = [
            item.get("id") for item in payload.get("data", []) if item.get("id")
        ]
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Could not reach LLM: {exc}")

    return {
        "connected": True,
        "model_available": req.model in model_ids if model_ids else None,
        "models": model_ids,
    }
