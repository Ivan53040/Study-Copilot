"""Settings endpoint: cloud-provider switch + API-key persistence.

Exercises the PUT /settings path that the desktop Settings screen drives —
selecting a cloud provider, saving its model, and persisting the API key to a
git-ignored .env (never the config file).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.main import app


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    (vault / "StudyCopilot").mkdir(parents=True)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"vault:\n  root: {vault.as_posix()}\n"
        f"database_url: sqlite:///{(tmp_path / 'test.db').as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STUDY_COPILOT_CONFIG", str(cfg))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    get_settings.cache_clear()
    yield cfg, vault
    # _set_env_var writes os.environ directly (bypassing monkeypatch) — clean up.
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    get_settings.cache_clear()


def _payload(vault, **overrides) -> dict:
    body = {
        "vault_root": str(vault),
        "default_provider": "lmstudio",
        "llm_base_url": "http://127.0.0.1:1234/v1",
        "llm_model": "local-model",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "gpt-4o-mini",
        "anthropic_model": "claude-opus-4-8",
        "embedding_provider": "hash",
        "embedding_model": "hash-256",
        "temperature": 0.1,
        "require_citations": True,
    }
    body.update(overrides)
    return body


def test_settings_exposes_cloud_fields(temp_config):
    data = TestClient(app).get("/settings").json()
    assert data["default_provider"] == "lmstudio"
    assert data["openai_model"] == "gpt-4o-mini"
    assert data["anthropic_model"] == "claude-opus-4-8"
    assert data["openai_key_set"] is False
    assert data["anthropic_key_set"] is False


def test_switch_to_anthropic_persists_key_to_env(temp_config):
    cfg, vault = temp_config
    client = TestClient(app)

    res = client.put(
        "/settings",
        json=_payload(vault, default_provider="anthropic", api_key="sk-ant-test123"),
    )
    assert res.status_code == 200, res.text
    saved = res.json()["settings"]
    assert saved["default_provider"] == "anthropic"
    assert saved["anthropic_key_set"] is True

    # Key lands in a sibling .env, never in the (potentially synced) config file.
    env_text = (cfg.parent / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY=sk-ant-test123" in env_text
    assert "sk-ant-test123" not in cfg.read_text(encoding="utf-8")


def test_switch_to_openai_saves_model_and_base_url(temp_config):
    cfg, vault = temp_config
    client = TestClient(app)

    res = client.put(
        "/settings",
        json=_payload(
            vault,
            default_provider="openai",
            openai_model="gpt-4o",
            openai_base_url="https://openrouter.ai/api/v1",
            api_key="sk-openai-test",
        ),
    )
    assert res.status_code == 200, res.text
    saved = res.json()["settings"]
    assert saved["default_provider"] == "openai"
    assert saved["openai_model"] == "gpt-4o"
    assert saved["openai_base_url"] == "https://openrouter.ai/api/v1"
    assert saved["openai_key_set"] is True


def test_unknown_provider_rejected(temp_config):
    _, vault = temp_config
    res = TestClient(app).put(
        "/settings", json=_payload(vault, default_provider="bogus")
    )
    assert res.status_code == 400


def test_save_preserves_config_comments(temp_config):
    cfg, vault = temp_config
    cfg.write_text("# KEEP THIS COMMENT\n" + cfg.read_text(encoding="utf-8"), "utf-8")

    res = TestClient(app).put("/settings", json=_payload(vault, llm_model="local-2"))
    assert res.status_code == 200, res.text

    rewritten = cfg.read_text(encoding="utf-8")
    assert "# KEEP THIS COMMENT" in rewritten  # comment survived the round-trip
    assert "local-2" in rewritten  # and the edit was applied
