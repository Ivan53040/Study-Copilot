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


class CloudFallbackConfig(BaseModel):
    enabled: bool = False
    require_approval: bool = True


class ModelsConfig(BaseModel):
    default_provider: str = "lmstudio"
    lmstudio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    cloud_fallback: CloudFallbackConfig = Field(default_factory=CloudFallbackConfig)


class RetrievalConfig(BaseModel):
    keyword_limit: int = 20
    vector_limit: int = 20
    final_context_limit: int = 8


class GenerationConfig(BaseModel):
    temperature: float = 0.1
    require_citations: bool = True


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
    external_sources: list[ExternalSource] = Field(default_factory=list)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    database_url: str = "sqlite:///./data/study_copilot.db"

    @property
    def output_root(self) -> Path:
        """The single writable folder (vault_root / StudyCopilot)."""
        return self.vault.root / "StudyCopilot"


def _default_config_path() -> Path:
    return Path(os.environ.get("STUDY_COPILOT_CONFIG", "config.yaml"))


def load_settings(config_path: str | Path | None = None) -> Settings:
    """Load and validate settings from a YAML file."""
    path = Path(config_path) if config_path else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path.resolve()}. "
            "Copy config.yaml and set STUDY_COPILOT_CONFIG if needed."
        )
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Settings.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings for use as a FastAPI dependency / app-wide singleton."""
    return load_settings()
