"""Grounded chat endpoint + conversation history."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.agent.study_agent import answer
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    course: str | None = None
    conversation_id: int | None = None


@router.post("/chat")
def post_chat(req: ChatRequest, settings: Settings = Depends(get_settings)) -> dict:
    result = answer(
        req.message,
        settings=settings,
        course=req.course,
        conversation_id=req.conversation_id,
    )
    return result.as_dict()


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
        return {
            "id": convo.id,
            "course": convo.course,
            "created_at": convo.created_at.isoformat(),
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "extra": m.extra,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }
