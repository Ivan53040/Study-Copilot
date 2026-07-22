"""Runtime-editable application settings."""

from __future__ import annotations

import io
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from app.config.settings import get_settings, load_settings
from app.database.db import reset_engine

router = APIRouter(prefix="/settings", tags=["settings"])

# Round-trip YAML: preserves the user's comments and layout across edits.
_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't wrap long paths/URLs onto multiple lines


def _load_config(path: Path) -> CommentedMap:
    with path.open("r", encoding="utf-8") as handle:
        data = _yaml.load(handle)
    return data if isinstance(data, CommentedMap) else CommentedMap()


def _dump_config(data: CommentedMap) -> str:
    buffer = io.StringIO()
    _yaml.dump(data, buffer)
    return buffer.getvalue()


class SettingsUpdate(BaseModel):
    vault_root: str = Field(min_length=1)
    lectures_root: str | None = None
    default_provider: str = "lmstudio"
    llm_base_url: str = Field(min_length=1)
    llm_model: str = Field(min_length=1)
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-opus-4-8"
    # Cloud API key for the selected provider. Write-only: persisted to a
    # git-ignored .env, never echoed back. Blank = keep the existing key.
    api_key: str | None = None
    embedding_provider: str = "lmstudio"
    embedding_base_url: str | None = None
    embedding_model: str = Field(min_length=1)
    task_models: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    chunk_tokens: int = Field(default=360, ge=100, le=8192)
    chunk_overlap_tokens: int = Field(default=50, ge=0, le=2048)
    min_chunk_tokens: int = Field(default=8, ge=0, le=200)
    temperature: float = Field(ge=0, le=2)
    require_citations: bool = True


class ConnectionTest(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)


def _config_path() -> Path:
    return Path(os.environ.get("STUDY_COPILOT_CONFIG", "config.yaml")).resolve()


def _cloud_key_env(provider: str, models: dict) -> str | None:
    """The env-var name holding the API key for a cloud provider, if any."""
    if provider == "openai":
        return models.get("openai", {}).get("api_key_env", "OPENAI_API_KEY")
    if provider == "anthropic":
        return models.get("anthropic", {}).get("api_key_env", "ANTHROPIC_API_KEY")
    return None


def _set_env_var(env_path: Path, key: str, value: str) -> None:
    """Upsert ``KEY=value`` in a git-ignored ``.env`` and apply it in-process."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out: list[str] = []
    replaced = False
    for line in lines:
        head = line.split("=", 1)[0].strip()
        if head == key and not line.lstrip().startswith("#"):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value


def _public_settings() -> dict:
    settings = get_settings()
    models = settings.models
    lectures_root = settings.lectures.root
    return {
        "vault_root": str(settings.vault.root),
        "vault_exists": settings.vault.root.is_dir(),
        "lectures_root": str(lectures_root) if lectures_root else None,
        "lectures_root_exists": lectures_root.is_dir() if lectures_root else None,
        "default_provider": models.default_provider,
        "llm_base_url": models.lmstudio.base_url,
        "llm_model": models.lmstudio.model,
        "openai_base_url": models.openai.base_url,
        "openai_model": models.openai.model,
        "anthropic_model": models.anthropic.model,
        "openai_key_set": bool(os.environ.get(models.openai.api_key_env)),
        "anthropic_key_set": bool(os.environ.get(models.anthropic.api_key_env)),
        "embedding_provider": settings.embeddings.provider,
        "embedding_base_url": settings.embeddings.base_url,
        "embedding_model": settings.embeddings.model,
        "task_models": settings.task_models.model_dump(),
        "chunk_tokens": settings.ingestion.chunk_tokens,
        "chunk_overlap_tokens": settings.ingestion.chunk_overlap_tokens,
        "min_chunk_tokens": settings.ingestion.min_chunk_tokens,
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
    if req.default_provider not in {"lmstudio", "echo", "openai", "anthropic"}:
        raise HTTPException(status_code=400, detail="Unsupported chat provider")
    if req.embedding_provider not in {"lmstudio", "hash"}:
        raise HTTPException(status_code=400, detail="Unsupported embedding provider")

    data = _load_config(config_path)

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
    openai = models.setdefault("openai", {})
    openai["base_url"] = req.openai_base_url.rstrip("/")
    openai["model"] = req.openai_model
    anthropic = models.setdefault("anthropic", {})
    anthropic["model"] = req.anthropic_model

    # Cloud API key (if supplied) goes to the git-ignored .env, never config.yaml.
    if req.api_key and req.api_key.strip():
        env_name = _cloud_key_env(req.default_provider, models)
        if env_name:
            _set_env_var(config_path.parent / ".env", env_name, req.api_key.strip())

    embeddings = data.setdefault("embeddings", {})
    embeddings["provider"] = req.embedding_provider
    embeddings["model"] = req.embedding_model
    embeddings["base_url"] = (
        req.embedding_base_url.rstrip("/") if req.embedding_base_url else None
    )

    valid_tasks = {
        "chat",
        "deep_ask",
        "transformations",
        "quiz_marking",
        "translation",
        "voice_notes",
        "wiki",
    }
    task_models = data.setdefault("task_models", {})
    for task, override in req.task_models.items():
        if task not in valid_tasks or not isinstance(override, dict):
            continue
        task_models[task] = {
            key: (value.rstrip("/") if key == "base_url" and value else value)
            for key, value in override.items()
            if key in {"provider", "model", "base_url"}
        }

    ingestion = data.setdefault("ingestion", {})
    ingestion["chunk_tokens"] = req.chunk_tokens
    ingestion["chunk_overlap_tokens"] = req.chunk_overlap_tokens
    ingestion["min_chunk_tokens"] = req.min_chunk_tokens

    generation = data.setdefault("generation", {})
    generation["temperature"] = req.temperature
    generation["require_citations"] = req.require_citations

    # Validate the complete config before replacing the live file.
    serialized = _dump_config(data)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=config_path.parent, delete=False, suffix=".yaml"
    ) as temp:
        temp.write(serialized)
        temp_path = Path(temp.name)
    try:
        load_settings(temp_path)
        os.replace(temp_path, config_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    get_settings.cache_clear()
    # Rebuild the engine so a changed database_url takes effect without a restart.
    reset_engine()
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
