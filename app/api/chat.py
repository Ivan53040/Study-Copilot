"""Grounded chat endpoint + conversation history."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, delete, func, select

from app.agent.study_agent import answer
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message

router = APIRouter(tags=["chat"])

_TITLE_CHARS = 80


class ChatRequest(BaseModel):
    message: str
    course: str | None = None
    scope_path: str | None = None
    study_set_id: int | None = None
    context_mode: str = "retrieval"
    context_items: list[dict] | None = None
    conversation_id: int | None = None


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


@router.post("/chat")
def post_chat(req: ChatRequest, settings: Settings = Depends(get_settings)) -> dict:
    result = answer(
        req.message,
        settings=settings,
        course=req.course,
        scope_path=req.scope_path,
        study_set_id=req.study_set_id,
        context_mode=req.context_mode,
        context_items=req.context_items,
        conversation_id=req.conversation_id,
    )
    return result.as_dict()


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
