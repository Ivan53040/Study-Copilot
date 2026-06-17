"""Shared test fixtures: an isolated temp vault + temp database."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import (
    ExternalSource,
    Settings,
    VaultConfig,
)
from app.database import db as db_module


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    """A small fake vault: one course folder + a denied .env + .obsidian dir."""
    root = tmp_path / "vault"
    course = root / "REIT6811 - Research Methods"
    course.mkdir(parents=True)

    (course / "REIT6811_Week1_Revision_Notes.md").write_text(
        "---\ntitle: Week 1 Revision\ncourse: REIT6811\nweek: 1\n---\n\n"
        "# Reliability\n\nReliability is consistency of measurement.\n\n"
        "## Validity\n\nValidity is measuring what you intend to measure.\n",
        encoding="utf-8",
    )
    (course / "REIT6811_Mock_Exam_1.md").write_text(
        "# Mock Exam 1\n\nQuestion 1: Define reliability.\n", encoding="utf-8"
    )

    # Things that must never be read.
    (root / ".env").write_text("SECRET=hunter2", encoding="utf-8")
    obsidian = root / ".obsidian" / "plugins"
    obsidian.mkdir(parents=True)
    (obsidian / "config.json").write_text("{}", encoding="utf-8")

    # StudyCopilot output folder (writable).
    (root / "StudyCopilot").mkdir()
    return root


@pytest.fixture
def settings(temp_vault: Path, tmp_path: Path) -> Settings:
    ext = tmp_path / "external_papers"
    ext.mkdir()
    return Settings(
        vault=VaultConfig(
            root=temp_vault,
            read_paths=["REIT6811 - Research Methods/**"],
            write_paths=["StudyCopilot/**"],
            denied_paths=["**/.obsidian/**", "**/.git/**", "**/.env"],
        ),
        external_sources=[
            ExternalSource(path=ext, course="REIT6811", source_type="past-paper")
        ],
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    )


@pytest.fixture
def db(settings: Settings):
    """Initialise a fresh database bound to the test settings."""
    db_module.reset_engine()
    db_module.init_db(settings)
    yield
    db_module.reset_engine()
