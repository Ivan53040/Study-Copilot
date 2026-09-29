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

import base64
import contextlib
import inspect
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from typing import Iterator, Protocol, runtime_checkable

import httpx

from app.config.settings import Settings


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str | list[dict]

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


def image_message(text: str, png: bytes) -> ChatMessage:
    """Use OpenAI-compatible image parts; cloud adapters translate as needed."""
    return ChatMessage(
        role="user",
        content=[{"type": "text", "text": text}, image_part(png)],
    )


def image_part(png: bytes) -> dict:
    encoded = base64.b64encode(png).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}


@dataclass
class ChatResponse:
    content: str
    model: str
    raw: dict | None = None


class ChatError(RuntimeError):
    pass


@dataclass
class StreamChunk:
    """One piece of a streamed reply: answer ``text`` or model ``thinking``."""

    kind: str  # "text" | "thinking" | "rethink" (text so far was thinking)
    text: str


_THINK_BLOCK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove a reasoning model's ``<think>…</think>`` block from its reply.

    Some chat templates open the block in the prompt, so the reply only carries
    the closing tag: everything before the last ``</think>`` is then reasoning.
    """
    cleaned = _THINK_BLOCK_RE.sub("", text)
    if "</think>" in cleaned.lower():
        cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1]
    return cleaned.strip()


class ThinkSplitter:
    """Route streamed text inside ``<think>…</think>`` to ``thinking`` chunks.

    Tags can arrive split across deltas, so a possible partial tag at the end
    of the buffer is held back until the next delta decides it.

    Some chat templates open the think block in the prompt, so the reply only
    carries the closing tag. When a ``</think>`` comes before any ``<think>``,
    the text already passed on as answer was reasoning: a ``rethink`` chunk
    says so (move it to the thinking), and what follows is the answer.
    """

    _OPEN, _CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False
        self._seen_tag = False

    @staticmethod
    def _partial_tag(buf: str, tags: tuple[str, ...]) -> int:
        """Length of the longest buffer tail that could start one of ``tags``."""
        lowered = buf.lower()
        for size in range(min(max(len(t) for t in tags) - 1, len(buf)), 0, -1):
            if any(tag.startswith(lowered[-size:]) for tag in tags):
                return size
        return 0

    def feed(self, text: str) -> list[StreamChunk]:
        self._buf += text
        out: list[StreamChunk] = []
        while self._buf:
            lowered = self._buf.lower()
            if not self._inside and not self._seen_tag:
                close = lowered.find(self._CLOSE)
                opening = lowered.find(self._OPEN)
                if close >= 0 and (opening < 0 or close < opening):
                    # Reasoning that began in the prompt: all of it so far.
                    out.append(StreamChunk("rethink", ""))
                    if close:
                        out.append(StreamChunk("thinking", self._buf[:close]))
                    self._buf = self._buf[close + len(self._CLOSE):]
                    self._seen_tag = True
                    continue
            tag = self._CLOSE if self._inside else self._OPEN
            kind = "thinking" if self._inside else "text"
            index = lowered.find(tag)
            if index >= 0:
                if index:
                    out.append(StreamChunk(kind, self._buf[:index]))
                self._buf = self._buf[index + len(tag):]
                self._inside = not self._inside
                self._seen_tag = True
                continue
            tags = (tag,) if self._inside or self._seen_tag else (self._OPEN, self._CLOSE)
            keep = self._partial_tag(self._buf, tags)
            emit = self._buf[: len(self._buf) - keep]
            if emit:
                out.append(StreamChunk(kind, emit))
            self._buf = self._buf[len(self._buf) - keep:]
            break
        return out

    def flush(self) -> list[StreamChunk]:
        rest, self._buf = self._buf, ""
        if not rest:
            return []
        return [StreamChunk("thinking" if self._inside else "text", rest)]


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
    extra_payload: dict | None = None,
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
    if extra_payload:
        payload.update(extra_payload)
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


class StreamCancel:
    """Ends model requests from another thread (the reader pressed Stop).

    Each request's socket is shut down. That wakes a read that is waiting on
    the model, even before the response headers arrive (a local model can
    spend a while reading a long prompt), and tells the model server the
    client left, so it can stop working on the reply.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self.cancelled = False

    def watch(self, sock: socket.socket) -> None:
        with self._lock:
            if not self.cancelled:
                self._sockets.append(sock)
                return
        _shutdown(sock)

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            sockets, self._sockets = self._sockets, []
        for sock in sockets:
            _shutdown(sock)

    def trace(self, event_name: str, info: dict) -> None:
        """httpcore trace hook: watch each new connection's socket."""
        if event_name == "connection.connect_tcp.complete":
            stream = info.get("return_value")
            sock = stream.get_extra_info("socket") if stream is not None else None
            if sock is not None:
                self.watch(sock)


def _shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # already closed


@contextlib.contextmanager
def _open_stream(
    url: str,
    *,
    json: dict,
    headers: dict | None,
    timeout: httpx.Timeout,
    cancel: StreamCancel | None = None,
) -> Iterator[httpx.Response]:
    """POST ``json`` and stream the response; ``cancel`` can end it early."""
    extensions = {"trace": cancel.trace} if cancel is not None else None
    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST", url, json=json, headers=headers, extensions=extensions
        ) as resp:
            yield resp


def _openai_chat_stream(
    *,
    base_url: str,
    model: str,
    messages: list[ChatMessage],
    temperature: float,
    max_tokens: int | None,
    timeout: float,
    api_key: str | None = None,
    provider_label: str = "LM Studio",
    extra_payload: dict | None = None,
    cancel: StreamCancel | None = None,
) -> Iterator[StreamChunk]:
    """Stream an OpenAI-compatible ``/chat/completions`` reply (SSE).

    Reasoning sent separately (``reasoning_content`` / ``reasoning``, as
    llama.cpp and LM Studio do) is yielded as ``thinking``. A server that
    ignores ``stream`` and answers with plain JSON still works.
    """
    payload: dict = {
        "model": model,
        "messages": [m.as_dict() for m in messages],
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if extra_payload:
        payload.update(extra_payload)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        with _open_stream(
            f"{base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            cancel=cancel,
        ) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise ChatError(
                    f"{provider_label} chat request failed: HTTP {resp.status_code} "
                    f"{resp.text[:300]}"
                )
            if "text/event-stream" not in resp.headers.get("content-type", ""):
                data = json.loads(resp.read() or b"{}")
                message = (data.get("choices") or [{}])[0].get("message") or {}
                reasoning = message.get("reasoning_content") or message.get("reasoning")
                if reasoning:
                    yield StreamChunk("thinking", reasoning)
                if message.get("content"):
                    yield StreamChunk("text", message["content"])
                return
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    continue
                if event.get("error"):
                    raise ChatError(f"{provider_label} stream error: {event['error']}")
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield StreamChunk("thinking", reasoning)
                    if delta.get("content"):
                        yield StreamChunk("text", delta["content"])
    except httpx.HTTPError as exc:
        raise ChatError(f"{provider_label} chat request failed: {exc}") from exc


class LMStudioChatAdapter:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        extra_payload: dict | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_name = model
        self._timeout = timeout
        self._extra_payload = extra_payload

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
            extra_payload=self._extra_payload,
        )

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        cancel: StreamCancel | None = None,
    ) -> Iterator[StreamChunk]:
        return _openai_chat_stream(
            base_url=self.base_url,
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._timeout,
            extra_payload=self._extra_payload,
            cancel=cancel,
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

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
        cancel: StreamCancel | None = None,
    ) -> Iterator[StreamChunk]:
        if not self._api_key:
            raise ChatError(
                "OpenAI API key is not set (see models.openai.api_key_env)."
            )
        return _openai_chat_stream(
            base_url=self.base_url,
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=self._timeout,
            api_key=self._api_key,
            provider_label="OpenAI",
            cancel=cancel,
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


def _anthropic_content(content: str | list[dict]) -> str | list[dict]:
    if isinstance(content, str):
        return content
    parts: list[dict] = []
    for part in content:
        if part.get("type") == "text":
            parts.append(part)
        elif part.get("type") == "image_url":
            url = part["image_url"]["url"]
            prefix = "data:image/png;base64,"
            if not url.startswith(prefix):
                raise ChatError("Only inline PNG images are supported")
            parts.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": url[len(prefix):]},
            })
    return parts


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

    def _request_kwargs(
        self, messages: list[ChatMessage], temperature: float, max_tokens: int | None
    ) -> dict:
        system = "\n\n".join(
            m.content for m in messages if m.role == "system" and isinstance(m.content, str)
        )
        convo = [
            {"role": m.role, "content": _anthropic_content(m.content)}
            for m in messages if m.role != "system"
        ]

        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": max_tokens or self._max_tokens,
            "messages": convo,
        }
        if system:
            kwargs["system"] = system
        if self._sends_temperature():
            kwargs["temperature"] = temperature
        return kwargs

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        client = self._ensure_client()
        kwargs = self._request_kwargs(messages, temperature, max_tokens)
        if not hasattr(client.messages, "stream"):
            response = self.generate(messages, temperature=temperature, max_tokens=max_tokens)
            yield StreamChunk("text", response.content)
            return
        try:
            with client.messages.stream(**kwargs) as stream:
                for text in stream.text_stream:
                    if text:
                        yield StreamChunk("text", text)
        except ChatError:
            raise
        except Exception as exc:  # anthropic.APIError and friends
            raise ChatError(f"Anthropic chat request failed: {exc}") from exc

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> ChatResponse:
        client = self._ensure_client()
        kwargs = self._request_kwargs(messages, temperature, max_tokens)

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
        joined = "\n".join(
            m.content if isinstance(m.content, str)
            else " ".join(part.get("text", "") for part in m.content if part.get("type") == "text")
            for m in messages if m.role == "user"
        )
        ids = self._SID_RE.findall(joined)
        if ids:
            content = (
                f"Based on the provided sources, here is the answer. [S{ids[0]}]"
            )
        else:
            content = "I don't know based on the available sources."
        return ChatResponse(content=content, model=self.model_name)

    def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> Iterator[StreamChunk]:
        content = self.generate(messages, temperature=temperature).content
        for word in re.findall(r"\S+\s*", content):
            yield StreamChunk("text", word)


def _takes_cancel(stream) -> bool:
    try:
        return "cancel" in inspect.signature(stream).parameters
    except (TypeError, ValueError):
        return False


def stream_reply(
    adapter: ChatAdapter,
    messages: list[ChatMessage],
    *,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    cancel: StreamCancel | None = None,
) -> Iterator[StreamChunk]:
    """Stream a reply from any adapter, splitting out ``<think>`` reasoning.

    Adapters without a ``stream`` method answer in one piece via ``generate``.
    ``cancel`` lets another thread end the request early (adapters that
    support it; the others finish their current piece first).
    """
    kwargs: dict = {"temperature": temperature}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    stream = getattr(adapter, "stream", None)
    if callable(stream):
        if cancel is not None and _takes_cancel(stream):
            kwargs["cancel"] = cancel
        source = stream(messages, **kwargs)
    else:
        response = adapter.generate(messages, **kwargs)
        source = iter([StreamChunk("text", response.content)])
    splitter = ThinkSplitter()
    for chunk in source:
        if chunk.kind == "text":
            yield from splitter.feed(chunk.text)
        else:
            yield chunk
    yield from splitter.flush()


def get_chat_adapter(
    settings: Settings, task: str = "chat", timeout: float | None = None
) -> ChatAdapter:
    override = getattr(settings.task_models, task, None)
    provider = (
        override.provider
        if override is not None and override.provider
        else settings.models.default_provider
    )
    if provider == "echo":
        return EchoChatAdapter()
    if provider == "openai":
        cfg = settings.models.openai
        return OpenAIChatAdapter(
            base_url=(override.base_url if override and override.base_url else cfg.base_url),
            model=(override.model if override and override.model else cfg.model),
            api_key=os.environ.get(cfg.api_key_env, ""),
            timeout=timeout or 120.0,
        )
    if provider == "anthropic":
        cfg = settings.models.anthropic
        return AnthropicChatAdapter(
            api_key=os.environ.get(cfg.api_key_env, ""),
            model=(override.model if override and override.model else cfg.model),
            max_tokens=cfg.max_tokens,
            timeout=timeout or 120.0,
        )
    lm = settings.models.lmstudio
    return LMStudioChatAdapter(
        base_url=(override.base_url if override and override.base_url else lm.base_url),
        model=(override.model if override and override.model else lm.model),
        timeout=timeout or 120.0,
    )
