"""Chat model adapters.

A provider-independent interface (plan §14), kept synchronous to match the rest
of the codebase. ``LMStudioChatAdapter`` calls an OpenAI-compatible
``/chat/completions`` endpoint; ``EchoChatAdapter`` is a deterministic offline
stand-in used by tests and when no model server is running.
"""

from __future__ import annotations

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
        payload: dict = {
            "model": self.model_name,
            "messages": [m.as_dict() for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ChatError(f"LM Studio chat request failed: {exc}") from exc
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return ChatResponse(content=content, model=self.model_name, raw=data)


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
    lm = settings.models.lmstudio
    return LMStudioChatAdapter(base_url=lm.base_url, model=lm.model)
