"""Chat-adapter selection and provider behaviour (offline).

These cover the cloud provider wiring added on top of the local LM Studio path:
the factory dispatch, the OpenAI bearer-auth header, and the Anthropic adapter's
system-prompt split + temperature handling. No network calls are made.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings, VaultConfig
from app.models import chat as chat_module
from app.models.chat import (
    AnthropicChatAdapter,
    ChatError,
    ChatMessage,
    EchoChatAdapter,
    LMStudioChatAdapter,
    OpenAIChatAdapter,
    get_chat_adapter,
)


# ---- factory dispatch ----


@pytest.mark.parametrize(
    "provider, expected",
    [
        ("echo", EchoChatAdapter),
        ("lmstudio", LMStudioChatAdapter),
        ("openai", OpenAIChatAdapter),
        ("anthropic", AnthropicChatAdapter),
        ("something-else", LMStudioChatAdapter),  # unknown -> local default
    ],
)
def test_factory_selects_provider(tmp_path, provider, expected):
    settings = Settings(vault=VaultConfig(root=tmp_path))
    settings.models.default_provider = provider
    assert isinstance(get_chat_adapter(settings), expected)


# ---- OpenAI adapter: bearer auth on an OpenAI-compatible endpoint ----


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_openai_adapter_sends_bearer_header(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse(
            {"choices": [{"message": {"content": "hi from gpt"}}]}
        )

    monkeypatch.setattr(chat_module.httpx, "post", fake_post)

    adapter = OpenAIChatAdapter(
        base_url="https://api.openai.com/v1", model="gpt-4o-mini", api_key="sk-test"
    )
    resp = adapter.generate([ChatMessage(role="user", content="hello")])

    assert resp.content == "hi from gpt"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "gpt-4o-mini"


def test_openai_adapter_requires_key():
    adapter = OpenAIChatAdapter(
        base_url="https://api.openai.com/v1", model="gpt-4o-mini", api_key=""
    )
    with pytest.raises(ChatError):
        adapter.generate([ChatMessage(role="user", content="hello")])


def test_lmstudio_adapter_sends_no_auth_header(monkeypatch):
    captured = {}

    def fake_post(url, *, json, headers, timeout):
        captured["headers"] = headers
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(chat_module.httpx, "post", fake_post)

    adapter = LMStudioChatAdapter(base_url="http://localhost:1234/v1", model="local")
    adapter.generate([ChatMessage(role="user", content="hello")])
    assert captured["headers"] is None  # local path stays unauthenticated


# ---- Anthropic adapter: system split + temperature handling ----


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeAnthropicMessage:
    def __init__(self, text, model):
        self.content = [_FakeBlock(text)]
        self.model = model


class _FakeAnthropicClient:
    def __init__(self):
        self.calls = []

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                return _FakeAnthropicMessage("claude says hi", kwargs["model"])

        self.messages = _Messages(self)


def test_anthropic_adapter_splits_system_and_drops_temperature():
    client = _FakeAnthropicClient()
    adapter = AnthropicChatAdapter(
        api_key="x", model="claude-opus-4-8", client=client
    )
    resp = adapter.generate(
        [
            ChatMessage(role="system", content="You are helpful."),
            ChatMessage(role="user", content="hi"),
        ],
        temperature=0.7,
    )

    assert resp.content == "claude says hi"
    call = client.calls[0]
    assert call["system"] == "You are helpful."
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    # Opus 4.8 rejects temperature -> it must be omitted.
    assert "temperature" not in call


def test_anthropic_adapter_keeps_temperature_for_sonnet():
    client = _FakeAnthropicClient()
    adapter = AnthropicChatAdapter(
        api_key="x", model="claude-sonnet-4-6", client=client
    )
    adapter.generate([ChatMessage(role="user", content="hi")], temperature=0.3)
    assert client.calls[0]["temperature"] == 0.3


def test_anthropic_adapter_wraps_errors():
    class _BoomClient:
        class messages:  # noqa: N801 - mimic SDK attribute access
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("network down")

    adapter = AnthropicChatAdapter(api_key="x", client=_BoomClient())
    with pytest.raises(ChatError):
        adapter.generate([ChatMessage(role="user", content="hi")])


def test_anthropic_adapter_requires_key_without_client():
    adapter = AnthropicChatAdapter(api_key="")
    with pytest.raises(ChatError):
        adapter.generate([ChatMessage(role="user", content="hi")])
