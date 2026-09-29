"""Grounded chat endpoint + conversation history."""

from __future__ import annotations

import functools
import json
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Iterator

import anyio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, delete, func, select

from app.agent.study_agent import ConversationEditError, answer, stream_answer
from app.logging_config import get_logger
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message

router = APIRouter(tags=["chat"])
logger = get_logger("api.chat")

_TITLE_CHARS = 80


class ChatRequest(BaseModel):
    message: str
    course: str | None = None
    scope_path: str | None = None
    study_set_id: int | None = None
    context_mode: str = "retrieval"
    context_items: list[dict] | None = None
    conversation_id: int | None = None
    # Answer from this open note (vault-relative) and the notes it links to.
    note_path: str | None = None
    # Edit / regenerate: replace this saved question and everything after it.
    replace_from_id: int | None = None

    def agent_kwargs(self) -> dict:
        return {
            "course": self.course,
            "scope_path": self.scope_path,
            "study_set_id": self.study_set_id,
            "context_mode": self.context_mode,
            "context_items": self.context_items,
            "conversation_id": self.conversation_id,
            "note_path": self.note_path or None,
            "replace_from_id": self.replace_from_id,
        }


class ConversationPatch(BaseModel):
    title: str | None = None


def _iso(value: datetime | None) -> str | None:
    """ISO timestamp that always carries a UTC offset.

    SQLite drops tzinfo on the way back out, and a naive ISO string would be
    read as *local* time by the browser, shifting every "2 hours ago" label.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _auto_title(first_message: str | None) -> str:
    text = re.sub(r"\s+", " ", first_message or "").strip()
    if not text:
        return "Untitled chat"
    if len(text) <= _TITLE_CHARS:
        return text
    return text[: _TITLE_CHARS - 1].rstrip() + "…"


def _request_error(exc: Exception) -> HTTPException | None:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (ConversationEditError, PermissionError, KeyError)):
        return HTTPException(status_code=400, detail=str(exc).strip("'\""))
    return None


@router.post("/chat")
def post_chat(req: ChatRequest, settings: Settings = Depends(get_settings)) -> dict:
    try:
        result = answer(req.message, settings=settings, **req.agent_kwargs())
    except Exception as exc:
        error = _request_error(exc)
        if error is None:
            raise
        raise error from exc
    return result.as_dict()


_END = object()


def _line(event: dict) -> bytes:
    return (json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8")


async def _ndjson(events: Iterator[dict]) -> AsyncIterator[bytes]:
    """Relay a blocking event generator as NDJSON without blocking the loop.

    When the client disconnects (or presses Stop) the response is cancelled at
    once, even while the model is still thinking: the stream's ``stop()`` then
    saves the partial answer straight away, and closing it ends the model
    request.
    """
    start_sent = False
    finished = False
    try:
        while True:
            try:
                event = await anyio.to_thread.run_sync(
                    next, events, _END, abandon_on_cancel=True
                )
            except Exception as exc:  # surface failures to the reader
                finished = True
                error = _request_error(exc)
                if error is None:
                    logger.exception("Chat stream failed")
                message = error.detail if error is not None else f"Chat failed: {exc}"
                yield _line({"type": "error", "message": message})
                return
            if event is _END:
                finished = True
                return
            # Counted as seen once we try to send it: if the reader drops just
            # then, keeping its question is safer than undoing one it saw.
            start_sent = start_sent or event.get("type") == "start"
            yield _line(event)
    finally:
        with anyio.CancelScope(shield=True):
            stop = getattr(events, "stop", None)
            if not finished and stop is not None:
                await anyio.to_thread.run_sync(
                    functools.partial(stop, start_delivered=start_sent)
                )
            await anyio.to_thread.run_sync(events.close)


@router.post("/chat/stream")
def post_chat_stream(
    req: ChatRequest, settings: Settings = Depends(get_settings)
) -> StreamingResponse:
    """Like ``POST /chat``, but streams the answer as NDJSON events.

    Events: ``start`` → ``thinking`` / ``delta`` … → ``done`` (the saved answer,
    same shape as ``POST /chat``) or ``error``.
    """
    events = stream_answer(req.message, settings=settings, **req.agent_kwargs())
    return StreamingResponse(
        _ndjson(events),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
def list_conversations(limit: int = 50, settings: Settings = Depends(get_settings)) -> dict:
    """Recent conversations, newest activity first (for the sidebar Recents)."""
    limit = max(1, min(limit, 200))
    with session_scope(settings) as session:
        stats = (
            select(
                Message.conversation_id.label("cid"),
                func.count(Message.id).label("n"),
                func.max(Message.created_at).label("last_at"),
                func.min(case((Message.role == "user", Message.id))).label("first_user_id"),
            )
            .group_by(Message.conversation_id)
            .subquery()
        )
        rows = session.execute(
            select(Conversation, stats.c.n, stats.c.last_at, Message.content)
            .join(stats, stats.c.cid == Conversation.id)
            .outerjoin(Message, Message.id == stats.c.first_user_id)
            .order_by(stats.c.last_at.desc(), Conversation.id.desc())
            .limit(limit)
        ).all()
        conversations = []
        for convo, count, last_at, first_message in rows:
            preview = re.sub(r"\s+", " ", first_message or "").strip()
            conversations.append(
                {
                    "id": convo.id,
                    "title": convo.title or _auto_title(first_message),
                    "custom_title": bool(convo.title),
                    "course": convo.course,
                    "created_at": _iso(convo.created_at),
                    "updated_at": _iso(last_at) or _iso(convo.created_at),
                    "message_count": int(count or 0),
                    "preview": preview[:240],
                }
            )
        return {"conversations": conversations}


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: int, settings: Settings = Depends(get_settings)
) -> dict:
    with session_scope(settings) as session:
        convo = session.get(Conversation, conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id)
        ).all()
        first_user = next((m.content for m in messages if m.role == "user"), None)
        return {
            "id": convo.id,
            "course": convo.course,
            "title": convo.title or _auto_title(first_user),
            "created_at": _iso(convo.created_at),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "extra": m.extra,
                    "created_at": _iso(m.created_at),
                }
                for m in messages
            ],
        }


@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: int,
    body: ConversationPatch,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Rename a conversation. A blank title reverts to the automatic one."""
    with session_scope(settings) as session:
        convo = session.get(Conversation, conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        title = re.sub(r"\s+", " ", body.title or "").strip()[:200]
        convo.title = title or None
        return {"id": convo.id, "title": convo.title}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int, settings: Settings = Depends(get_settings)
) -> dict:
    with session_scope(settings) as session:
        convo = session.get(Conversation, conversation_id)
        if convo is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        session.execute(delete(Message).where(Message.conversation_id == conversation_id))
        session.delete(convo)
        return {"deleted": conversation_id}
