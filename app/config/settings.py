"""Application settings, loaded from a YAML config file.

The config file path comes from the ``STUDY_COPILOT_CONFIG`` environment
variable (falling back to ``config.yaml`` in the current working directory).
Everything is validated by Pydantic so a malformed config fails loudly at
startup rather than deep inside the pipeline.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class ExternalSource(BaseModel):
    """A read-only directory of material that lives outside the vault."""

    path: Path
    course: str | None = None
    source_type: str | None = None


class VaultConfig(BaseModel):
    root: Path
    read_paths: list[str] = Field(default_factory=list)
    write_paths: list[str] = Field(default_factory=lambda: ["StudyCopilot/**"])
    denied_paths: list[str] = Field(default_factory=list)

    @field_validator("root")
    @classmethod
    def _expand_root(cls, v: Path) -> Path:
        return Path(os.path.expanduser(str(v)))


class LMStudioConfig(BaseModel):
    base_url: str = "http://127.0.0.1:1234/v1"
    model: str = "local-model"


class OpenAIConfig(BaseModel):
    """Cloud OpenAI (or any OpenAI-compatible gateway: OpenRouter, Groq, …).

    The API key is read from the environment (``api_key_env``), never stored in
    the config file.
    """

    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"


class AnthropicConfig(BaseModel):
    """Cloud Anthropic (Claude). Uses the official ``anthropic`` SDK.

    The API key is read from the environment (``api_key_env``), never stored in
    the config file.
    """

    model: str = "claude-opus-4-8"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_tokens: int = 4096


class CloudFallbackConfig(BaseModel):
    enabled: bool = False
    require_approval: bool = True


class ModelsConfig(BaseModel):
    # "lmstudio" (local, default), "openai", "anthropic", or "echo" (offline test).
    default_provider: str = "lmstudio"
    lmstudio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)
    cloud_fallback: CloudFallbackConfig = Field(default_factory=CloudFallbackConfig)


class EmbeddingsConfig(BaseModel):
    # "lmstudio" (OpenAI-compatible /embeddings) or "hash" (offline fallback).
    provider: str = "lmstudio"
    model: str = "text-embedding-nomic-embed-text-v1.5"
    base_url: str | None = None  # defaults to models.lmstudio.base_url
    batch_size: int = 32
    # Dimension for the offline "hash" provider.
    hash_dim: int = 256


class IngestionConfig(BaseModel):
    # Approximate-token chunking; keeps old citation metadata but avoids
    # model-context surprises from purely character-based chunks.
    chunk_tokens: int = 360
    chunk_overlap_tokens: int = 50
    min_chunk_tokens: int = 4


class RetrievalConfig(BaseModel):
    keyword_limit: int = 20
    vector_limit: int = 20
    final_context_limit: int = 8
    # Reciprocal-rank-fusion constant and trust weighting for hybrid search.
    rrf_k: int = 60
    trust_weight: float = 0.15


class GenerationConfig(BaseModel):
    temperature: float = 0.1
    require_citations: bool = True


class TaskModelOverride(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None


class TaskModelsConfig(BaseModel):
    chat: TaskModelOverride = Field(default_factory=TaskModelOverride)
    deep_ask: TaskModelOverride = Field(default_factory=TaskModelOverride)
    transformations: TaskModelOverride = Field(default_factory=TaskModelOverride)
    quiz_marking: TaskModelOverride = Field(default_factory=TaskModelOverride)
    translation: TaskModelOverride = Field(default_factory=TaskModelOverride)
    voice_notes: TaskModelOverride = Field(default_factory=TaskModelOverride)
    wiki: TaskModelOverride = Field(default_factory=TaskModelOverride)


class WikiConfig(BaseModel):
    """LLM-built wiki of interlinked entity/concept pages in the vault."""

    # Vault-relative root; per-course wikis live in subfolders.
    root: str = "StudyCopilot/Wiki"
    # Cap on entity/concept pages the LLM may emit per source document.
    max_pages_per_source: int = 6
    # Clipping budgets (characters) to keep prompts inside local context windows.
    max_source_chars: int = 24000
    max_index_chars: int = 8000
    max_existing_page_chars: int = 3000
    # Communities with cohesion below this are flagged as sparse knowledge areas.
    min_cohesion: float = 0.15
    # Re-ask the model this many times when it returns unparseable JSON.
    json_retries: int = 1
    # Long-running source builds can exceed normal chat latency, especially
    # when the local model server queues several concurrent requests.
    chat_timeout_seconds: float = 900.0
    # Sources processed in parallel (match the LLM server's concurrency;
    # LM Studio default is 4). Writes are serialized regardless.
    max_concurrent_sources: int = 4


class LecturesConfig(BaseModel):
    """Folder that holds lecture PDFs / PowerPoint files."""

    root: Path | None = None

    @field_validator("root")
    @classmethod
    def _expand_root(cls, v: Path | None) -> Path | None:
        return Path(os.path.expanduser(str(v))) if v is not None else None


class VoiceNotesConfig(BaseModel):
    """Local speech-to-text settings for uploaded or recorded voice notes."""

    enabled: bool = True
    whisper_model_path: Path | None = None
    whisper_cli_path: str = "whisper-cli"
    ffmpeg_path: str = "ffmpeg"
    audio_root: Path = Path("./data/voice_notes")
    keep_audio: bool = False
    language: str = "auto"
    max_upload_mb: int = 250

    @field_validator("whisper_model_path", "audio_root")
    @classmethod
    def _expand_path(cls, v: Path | None) -> Path | None:
        return Path(os.path.expanduser(str(v))) if v is not None else None


class WorkspaceConfig(BaseModel):
    """Standalone note-workspace settings (browse/edit the whole vault)."""

    allow_edit: bool = True
    backup_on_edit: bool = True
    # Keep at most this many automatic backups per note (0 = keep all).
    max_backups_per_note: int = 20
    editable_extensions: list[str] = Field(
        default_factory=lambda: [".md", ".markdown", ".txt"]
    )


class SyncConfig(BaseModel):
    """One-way sync from the local working vault to iCloud.

    Source is always ``vault.root``; destination is ``icloud_root``.
    """

    enabled: bool = False
    icloud_root: Path | None = None
    # "twoway" = bidirectional; "mirror" = exact one-way (deletes extras);
    # "additive" = one-way, never delete.
    mode: str = "mirror"
    # Run the sync loop inside the app process. Leave False if a Windows
    # scheduled task handles syncing (avoids double-running).
    run_in_app: bool = False
    interval_minutes: int = 5
    # Directories (relative names) to skip when syncing.
    exclude_dirs: list[str] = Field(default_factory=list)

    @field_validator("icloud_root")
    @classmethod
    def _expand_icloud(cls, v: Path | None) -> Path | None:
        return Path(os.path.expanduser(str(v))) if v is not None else None


class Settings(BaseModel):
    vault: VaultConfig
    lectures: LecturesConfig = Field(default_factory=LecturesConfig)
    voice_notes: VoiceNotesConfig = Field(default_factory=VoiceNotesConfig)
    external_sources: list[ExternalSource] = Field(default_factory=list)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    task_models: TaskModelsConfig = Field(default_factory=TaskModelsConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    wiki: WikiConfig = Field(default_factory=WikiConfig)
    database_url: str = "sqlite:///./data/study_copilot.db"

    @property
    def output_root(self) -> Path:
        """The single writable folder (vault_root / StudyCopilot)."""
        return self.vault.root / "StudyCopilot"


def _default_config_path() -> Path:
    return Path(os.environ.get("STUDY_COPILOT_CONFIG", "config.yaml"))


def _load_env_file(directory: Path) -> None:
    """Load cloud API keys from a sibling ``.env`` (real env vars still win).

    Keys (OPENAI_API_KEY / ANTHROPIC_API_KEY) are kept out of the committed
    ``config.yaml``; the desktop Settings screen writes them here instead.
    """
    env_path = directory / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv ships with uvicorn[standard]
        return
    load_dotenv(env_path, override=False)


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load and validate settings from a YAML file."""
    path = Path(config_path) if config_path else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path.resolve()}. "
            "Copy config.yaml and set STUDY_COPILOT_CONFIG if needed."
        )
    _load_env_file(path.resolve().parent)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for use as a FastAPI dependency / app-wide singleton."""
    return load_settings()
