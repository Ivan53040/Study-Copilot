"""Chat model adapters.

A provider-independent interface (plan §14), kept synchronous to match the rest
of the codebase:

* ``LMStudioChatAdapter`` — local, OpenAI-compatible ``/chat/completions``.
* ``OpenAIChatAdapter`` — cloud OpenAI (or any OpenAI-compatible gateway),
  same wire format plus a bearer token.
* ``AnthropicChatAdapter`` — cloud Claude via the official ``anthropic`` SDK.
* ``EchoChatAdapter`` — a deterministic offline stand-in used by tests and when
  no model server is running.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.config.settings import Settings


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResponse:
    content: str
    model: str
    raw: dict | None = None


class ChatError(RuntimeError):
    pass


@runtime_checkable
class ChatAdapter(Protocol):
    model_name: str

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        ...


def _openai_chat_completion(
    *,
    base_url: str,
    model: str,
    messages: list[ChatMessage],
    temperature: float,
    max_tokens: int | None,
    timeout: float,
    api_key: str | None = None,
    provider_label: str = "LM Studio",
) -> ChatResponse:
    """POST to an OpenAI-compatible ``/chat/completions`` endpoint.

    Shared by the local LM Studio adapter and the cloud OpenAI adapter; the only
    difference is the bearer ``api_key`` (cloud) vs none (local).
    """
    payload: dict = {
        "model": model,
        "messages": [m.as_dict() for m in messages],
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ChatError(f"{provider_label} chat request failed: {exc}") from exc
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return ChatResponse(content=content, model=model, raw=data)


class LMStudioChatAdapter:
    def __init__(self, base_url: str, model: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._timeout = timeout

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        return _openai_chat_completion(
            base_url=self.base_url,
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._timeout,
        )


class OpenAIChatAdapter:
    """Cloud OpenAI (or any OpenAI-compatible gateway) over HTTPS with a key."""

    def __init__(
        self, base_url: str, model: str, api_key: str, timeout: float = 120.0
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._api_key = api_key
        self._timeout = timeout

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        if not self._api_key:
            raise ChatError(
                "OpenAI API key is not set (see models.openai.api_key_env)."
            )
        return _openai_chat_completion(
            base_url=self.base_url,
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._timeout,
            api_key=self._api_key,
            provider_label="OpenAI",
        )


# Claude models that reject the `temperature` sampling parameter (HTTP 400):
# Opus 4.7+, Fable, and Mythos. Sonnet/Haiku and older Opus still accept it.
_CLAUDE_NO_TEMPERATURE_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-4-9",
    "claude-fable",
    "claude-mythos",
)


class AnthropicChatAdapter:
    """Cloud Claude via the official ``anthropic`` SDK.

    Translates the codebase's flat message list (which carries the system prompt
    as a ``role="system"`` message) into the Messages API shape, where the system
    prompt is a top-level argument. ``temperature`` is dropped for models that
    reject it (Opus 4.7+/Fable/Mythos).

    The SDK is imported lazily so the rest of the app runs without the package
    installed; an explicit ``client`` can be injected for testing.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-4-8",
        max_tokens: int = 4096,
        timeout: float = 120.0,
        client=None,
    ):
        self.model_name = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._client = client

    def _ensure_client(self):
        if self._client is None:
            if not self._api_key:
                raise ChatError(
                    "Anthropic API key is not set (see models.anthropic.api_key_env)."
                )
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depends on env
                raise ChatError(
                    "The 'anthropic' package is required for the Claude provider "
                    "(pip install anthropic)."
                ) from exc
            self._client = anthropic.Anthropic(
                api_key=self._api_key, timeout=self._timeout
            )
        return self._client

    def _sends_temperature(self) -> bool:
        return not self.model_name.lower().startswith(
            _CLAUDE_NO_TEMPERATURE_PREFIXES
        )

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        client = self._ensure_client()
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        convo = [m.as_dict() for m in messages if m.role != "system"]

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": max_tokens or self._max_tokens,
            "messages": convo,
        }
        if system:
            kwargs["system"] = system
        if self._sends_temperature():
            kwargs["temperature"] = temperature

        try:
            resp = client.messages.create(**kwargs)
        except ChatError:
            raise
        except Exception as exc:  # anthropic.APIError and friends
            raise ChatError(f"Anthropic chat request failed: {exc}") from exc

        text = "".join(
            block.text
            for block in resp.content
            if getattr(block, "type", None) == "text"
        )
        return ChatResponse(
            content=text, model=getattr(resp, "model", self.model_name), raw=None
        )


class EchoChatAdapter:
    """Offline adapter: answers by quoting the first cited source.

    Deterministic so tests can assert behaviour without a model. It honours the
    grounding contract: if the context has sources it cites ``[S1]``; otherwise
    it declines.
    """

    model_name = "echo"
    _SID_RE = re.compile(r"\[S(\d+)\]")

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        joined = "\n".join(m.content for m in messages if m.role == "user")
        ids = self._SID_RE.findall(joined)
        if ids:
            content = (
                f"Based on the provided sources, here is the answer. [S{ids[0]}]"
            )
        else:
            content = "I don't know based on the available sources."
        return ChatResponse(content=content, model=self.model_name)


def get_chat_adapter(settings: Settings) -> ChatAdapter:
    provider = settings.models.default_provider
    if provider == "echo":
        return EchoChatAdapter()
    if provider == "openai":
        cfg = settings.models.openai
        return OpenAIChatAdapter(
            base_url=cfg.base_url,
            model=cfg.model,
            api_key=os.environ.get(cfg.api_key_env, ""),
        )
    if provider == "anthropic":
        cfg = settings.models.anthropic
        return AnthropicChatAdapter(
            api_key=os.environ.get(cfg.api_key_env, ""),
            model=cfg.model,
            max_tokens=cfg.max_tokens,
        )
    lm = settings.models.lmstudio
    return LMStudioChatAdapter(base_url=lm.base_url, model=lm.model)
