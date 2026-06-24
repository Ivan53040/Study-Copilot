"""Grounded Q&A agent: retrieve -> build context -> generate -> validate -> persist."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlalchemy import select

from app.agent.context import build_context
from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agent.validation import validate_answer
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message
from app.logging_config import get_logger
from app.models.chat import ChatAdapter, ChatError, ChatMessage, get_chat_adapter
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter

logger = get_logger("agent")

_NO_SOURCES = "I don't have that in your materials."
_HISTORY_TURNS = 6  # how many prior messages to replay for context


@dataclass
class AnswerResult:
    conversation_id: int
    answer: str
    citations: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    used_vector: bool = False
    model: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _load_history(session, conversation_id: int) -> list[ChatMessage]:
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(_HISTORY_TURNS)
    ).all()
    rows.reverse()
    return [ChatMessage(role=m.role, content=m.content) for m in rows]


def answer(
    question: str,
    *,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    course: str | None = None,
    scope_path: str | None = None,
    conversation_id: int | None = None,
) -> AnswerResult:
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings)
    flt = MetadataFilter(course=course, path_prefix=scope_path)

    retrieval = search(question, settings=settings, flt=flt)
    if course or scope_path:
        lecture_root = (
            Path(settings.vault.root).expanduser().resolve() / "Lecture Materials"
        )
        if lecture_root.is_dir():
            lecture_retrieval = search(
                question,
                settings=settings,
                flt=MetadataFilter(path_prefix=str(lecture_root)),
                final_limit=max(3, settings.retrieval.final_context_limit // 2),
            )
            seen = {hit.chunk_id for hit in retrieval.hits}
            combined = list(retrieval.hits)
            combined.extend(
                hit for hit in lecture_retrieval.hits if hit.chunk_id not in seen
            )
            combined.sort(
                key=lambda hit: (
                    1 if course and hit.course == course else 0,
                    hit.score,
                ),
                reverse=True,
            )
            retrieval.hits = combined[: settings.retrieval.final_context_limit]
            retrieval.used_vector = (
                retrieval.used_vector or lecture_retrieval.used_vector
            )
    context = build_context(
        retrieval.hits, max_chars=_context_budget(settings)
    )
    source_dicts = [
        {**hit.as_dict(include_content=False), "marker": sid}
        for sid, hit in context.sources.items()
    ]

    with session_scope(settings) as session:
        convo = _get_or_create_conversation(session, conversation_id, course)
        session.add(Message(conversation_id=convo.id, role="user", content=question))

        if context.is_empty:
            result = AnswerResult(
                conversation_id=convo.id,
                answer=_NO_SOURCES,
                used_vector=retrieval.used_vector,
                model=adapter.model_name,
                warnings=["No relevant sources found."],
            )
            session.add(
                Message(
                    conversation_id=convo.id,
                    role="assistant",
                    content=_NO_SOURCES,
                    extra={"warnings": result.warnings},
                )
            )
            return result

        messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
        messages += _load_history(session, convo.id)
        messages.append(
            ChatMessage(
                role="user", content=build_user_prompt(question, context.text)
            )
        )

        try:
            response = adapter.generate(
                messages, temperature=settings.generation.temperature
            )
            answer_text = response.content.strip()
            model_name = response.model
            check = validate_answer(
                answer_text,
                context.sources,
                require_citations=settings.generation.require_citations,
            )
            citations = check.valid_citations
            warnings = check.warnings
        except ChatError as exc:
            # Model down: still return the sources we retrieved, with a note.
            logger.warning("Chat model unavailable: %s", exc)
            answer_text = (
                "The local model is unavailable, so I can't write an answer, "
                "but I found relevant sources below. Start LM Studio (or set "
                "models.default_provider) to get a written answer."
            )
            model_name = adapter.model_name
            citations = []
            warnings = [f"Chat model unavailable: {exc}"]

        result = AnswerResult(
            conversation_id=convo.id,
            answer=answer_text,
            citations=citations,
            sources=source_dicts,
            warnings=warnings,
            used_vector=retrieval.used_vector,
            model=model_name,
        )
        session.add(
            Message(
                conversation_id=convo.id,
                role="assistant",
                content=answer_text,
                extra={
                    "citations": citations,
                    "warnings": warnings,
                    "sources": source_dicts,
                },
            )
        )

    return result


def _context_budget(settings: Settings) -> int:
    # Roughly cap context; final_context_limit hits * ~ per-chunk size.
    return max(2000, settings.retrieval.final_context_limit * 900)


def _get_or_create_conversation(
    session, conversation_id: int | None, course: str | None
) -> Conversation:
    if conversation_id is not None:
        convo = session.get(Conversation, conversation_id)
        if convo is not None:
            return convo
    convo = Conversation(course=course)
    session.add(convo)
    session.flush()
    return convo
