"""Grounded Q&A agent: retrieve -> build context -> generate -> validate -> persist."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from sqlalchemy import delete, select

from app.agent.context import ContextBlock, build_context
from app.agent.manual_context import manual_hits
from app.agent.note_scope import note_scope_hits
from app.agent.prompts import SYSTEM_PROMPT, build_user_prompt
from app.agent.validation import validate_answer
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message
from app.ingestion.page_images import render_page
from app.logging_config import get_logger
from app.models.chat import (
    ChatAdapter,
    ChatError,
    ChatMessage,
    StreamChunk,
    get_chat_adapter,
    image_part,
    stream_reply,
    strip_think,
)
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter
from app.study_sets.service import resolve_scope

logger = get_logger("agent")

_NO_SOURCES = "I don't have that in your materials."
_MODEL_DOWN = (
    "The local model is unavailable, so I can't write an answer, "
    "but I found relevant sources below. Start LM Studio (or set "
    "models.default_provider) to get a written answer."
)
_VISION_FALLBACK = "Visual model unavailable; answered from text only."
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
    user_message_id: int | None = None
    message_id: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class PreparedAnswer:
    """Everything decided before the model is called (and the question saved)."""

    conversation_id: int
    user_message_id: int
    adapter: ChatAdapter
    context: ContextBlock
    source_dicts: list[dict]
    used_vector: bool
    messages: list[ChatMessage]  # empty when there is no context to answer from
    text_prompt: str = ""
    image_count: int = 0


class ConversationEditError(ValueError):
    """``replace_from_id`` does not name a question in this conversation."""


def _load_history(session, conversation_id: int) -> list[ChatMessage]:
    rows = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(_HISTORY_TURNS)
    ).all()
    rows.reverse()
    return [ChatMessage(role=m.role, content=m.content) for m in rows]


def _truncate_from(session, conversation_id: int, message_id: int) -> None:
    """Drop a question and everything after it (to edit or regenerate it)."""
    target = session.get(Message, message_id)
    if target is None or target.conversation_id != conversation_id or target.role != "user":
        raise ConversationEditError("That question is not part of this conversation.")
    session.execute(
        delete(Message).where(
            Message.conversation_id == conversation_id, Message.id >= message_id
        )
    )


def _retrieve(
    question: str,
    *,
    settings: Settings,
    course: str | None,
    scope_path: str | None,
    study_set_id: int | None,
    context_mode: str,
    context_items: list[dict] | None,
    note_path: str | None,
) -> tuple[list, bool, str | None]:
    """``(hits, used_vector, course)`` for the question's scope."""
    if note_path:
        hits, used_vector = note_scope_hits(question, note_path, settings)
        return hits, used_vector, course

    resolved = resolve_scope(
        settings=settings,
        study_set_id=study_set_id,
        course=course,
        scope_path=scope_path,
    )
    flt = MetadataFilter(
        course=resolved.course,
        path_prefix=resolved.scope_path,
        document_ids=resolved.document_ids or None,
    )

    all_context_items = list(resolved.context_items)
    all_context_items.extend(context_items or [])
    manual = manual_hits(all_context_items, settings=settings)
    if context_mode not in {"retrieval", "manual", "hybrid"}:
        context_mode = "retrieval"

    retrieval = (
        search(question, settings=settings, flt=flt)
        if context_mode != "manual"
        else None
    )
    if retrieval is not None and (resolved.course or resolved.scope_path):
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
    retrieval_hits = retrieval.hits if retrieval is not None else []
    if context_mode == "manual":
        return manual, False, resolved.course
    used_vector = bool(retrieval and retrieval.used_vector)
    if context_mode == "hybrid":
        seen = {hit.chunk_id for hit in manual}
        hits = manual + [hit for hit in retrieval_hits if hit.chunk_id not in seen]
        return hits, used_vector, resolved.course
    return retrieval_hits, used_vector, resolved.course


def prepare_answer(
    question: str,
    *,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    course: str | None = None,
    scope_path: str | None = None,
    study_set_id: int | None = None,
    context_mode: str = "retrieval",
    context_items: list[dict] | None = None,
    conversation_id: int | None = None,
    note_path: str | None = None,
    replace_from_id: int | None = None,
) -> PreparedAnswer:
    """Retrieve context, save the question and build the model prompt.

    The question is committed before the model runs, so no database write is
    held open during a long generation.
    """
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings, task="chat")
    hits, used_vector, convo_course = _retrieve(
        question,
        settings=settings,
        course=course,
        scope_path=scope_path,
        study_set_id=study_set_id,
        context_mode=context_mode,
        context_items=context_items,
        note_path=note_path,
    )
    budget = _context_budget(settings)
    if note_path:
        budget = max(budget, 12000)
    context = build_context(hits, max_chars=budget)
    source_dicts = [
        {**hit.as_dict(include_content=False), "marker": sid}
        for sid, hit in context.sources.items()
    ]

    with session_scope(settings) as session:
        convo = _get_or_create_conversation(session, conversation_id, convo_course)
        if replace_from_id is not None:
            _truncate_from(session, convo.id, replace_from_id)
        history = _load_history(session, convo.id)
        user_message = Message(conversation_id=convo.id, role="user", content=question)
        session.add(user_message)
        session.flush()
        prepared = PreparedAnswer(
            conversation_id=convo.id,
            user_message_id=user_message.id,
            adapter=adapter,
            context=context,
            source_dicts=source_dicts,
            used_vector=used_vector,
            messages=[],
        )

    if context.is_empty:
        return prepared
    text_prompt = build_user_prompt(question, context.text)
    visual_message, image_count = (
        _message_with_source_pages(text_prompt, context.sources, settings)
        if settings.generation.include_page_images
        else (ChatMessage(role="user", content=text_prompt), 0)
    )
    prepared.messages = [
        ChatMessage(role="system", content=SYSTEM_PROMPT),
        *history,
        visual_message,
    ]
    prepared.text_prompt = text_prompt
    prepared.image_count = image_count
    return prepared


def _save_reply(
    prepared: PreparedAnswer,
    settings: Settings,
    *,
    answer_text: str,
    model: str,
    citations: list[dict],
    warnings: list[str],
    sources: list[dict],
) -> AnswerResult:
    with session_scope(settings) as session:
        extra: dict = {"warnings": warnings}
        if sources or citations:
            extra = {"citations": citations, "warnings": warnings, "sources": sources}
        message = Message(
            conversation_id=prepared.conversation_id,
            role="assistant",
            content=answer_text,
            extra=extra,
        )
        session.add(message)
        session.flush()
        message_id = message.id
    return AnswerResult(
        conversation_id=prepared.conversation_id,
        answer=answer_text,
        citations=citations,
        sources=sources,
        warnings=warnings,
        used_vector=prepared.used_vector,
        model=model,
        user_message_id=prepared.user_message_id,
        message_id=message_id,
    )


def _save_no_sources(prepared: PreparedAnswer, settings: Settings) -> AnswerResult:
    return _save_reply(
        prepared,
        settings,
        answer_text=_NO_SOURCES,
        model=prepared.adapter.model_name,
        citations=[],
        warnings=["No relevant sources found."],
        sources=[],
    )


def _save_generated(
    prepared: PreparedAnswer,
    settings: Settings,
    *,
    text: str,
    model: str,
    extra_warnings: list[str],
    error: ChatError | None = None,
    stopped: bool = False,
) -> AnswerResult:
    """Validate and save a model reply (whole, partial, or missing)."""
    answer_text = strip_think(text)
    if error is not None and not answer_text:
        # Model down: still return the sources we retrieved, with a note.
        logger.warning("Chat model unavailable: %s", error)
        return _save_reply(
            prepared,
            settings,
            answer_text=_MODEL_DOWN,
            model=prepared.adapter.model_name,
            citations=[],
            warnings=[f"Chat model unavailable: {error}"],
            sources=prepared.source_dicts,
        )
    check = validate_answer(
        answer_text,
        prepared.context.sources,
        require_citations=settings.generation.require_citations and not stopped,
    )
    warnings = check.warnings + extra_warnings
    if error is not None:
        logger.warning("Chat model stopped mid-answer: %s", error)
        warnings.append(f"The model stopped before finishing: {error}")
    if stopped:
        warnings.append("Stopped before the answer was finished.")
    return _save_reply(
        prepared,
        settings,
        answer_text=answer_text,
        model=model,
        citations=check.valid_citations,
        warnings=warnings,
        sources=prepared.source_dicts,
    )


def answer(
    question: str,
    *,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    course: str | None = None,
    scope_path: str | None = None,
    study_set_id: int | None = None,
    context_mode: str = "retrieval",
    context_items: list[dict] | None = None,
    conversation_id: int | None = None,
    note_path: str | None = None,
    replace_from_id: int | None = None,
) -> AnswerResult:
    settings = settings or get_settings()
    prepared = prepare_answer(
        question,
        settings=settings,
        adapter=adapter,
        course=course,
        scope_path=scope_path,
        study_set_id=study_set_id,
        context_mode=context_mode,
        context_items=context_items,
        conversation_id=conversation_id,
        note_path=note_path,
        replace_from_id=replace_from_id,
    )
    if prepared.context.is_empty:
        return _save_no_sources(prepared, settings)

    adapter = prepared.adapter
    temperature = settings.generation.temperature
    notes: list[str] = []
    try:
        try:
            response = adapter.generate(prepared.messages, temperature=temperature)
        except ChatError:
            if not prepared.image_count:
                raise
            # A configured text-only model can still answer from the indexed text.
            response = adapter.generate(_text_only(prepared), temperature=temperature)
            notes.append(_VISION_FALLBACK)
    except ChatError as exc:
        return _save_generated(
            prepared, settings, text="", model=adapter.model_name,
            extra_warnings=[], error=exc,
        )
    return _save_generated(
        prepared, settings, text=response.content, model=response.model,
        extra_warnings=notes,
    )


def stream_answer(
    question: str,
    *,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
    course: str | None = None,
    scope_path: str | None = None,
    study_set_id: int | None = None,
    context_mode: str = "retrieval",
    context_items: list[dict] | None = None,
    conversation_id: int | None = None,
    note_path: str | None = None,
    replace_from_id: int | None = None,
) -> Iterator[dict]:
    """Answer while the model writes, as a sequence of events.

    ``start`` (conversation, saved question id, sources) → ``thinking`` /
    ``delta`` pieces → ``done`` (the saved answer, like :func:`answer`).
    Closing the generator early (the reader went away or pressed Stop) saves
    what was written so far.
    """
    settings = settings or get_settings()
    prepared = prepare_answer(
        question,
        settings=settings,
        adapter=adapter,
        course=course,
        scope_path=scope_path,
        study_set_id=study_set_id,
        context_mode=context_mode,
        context_items=context_items,
        conversation_id=conversation_id,
        note_path=note_path,
        replace_from_id=replace_from_id,
    )
    yield {
        "type": "start",
        "conversation_id": prepared.conversation_id,
        "user_message_id": prepared.user_message_id,
        "sources": prepared.source_dicts,
        "used_vector": prepared.used_vector,
        "model": prepared.adapter.model_name,
    }
    if prepared.context.is_empty:
        yield {"type": "done", **_save_no_sources(prepared, settings).as_dict()}
        return

    parts: list[str] = []
    notes: list[str] = []
    saved = False
    try:
        error: ChatError | None = None
        chunks = _stream_generation(prepared, settings, notes)
        try:
            for chunk in chunks:
                if chunk.kind == "text":
                    parts.append(chunk.text)
                    yield {"type": "delta", "text": chunk.text}
                elif chunk.text:
                    yield {"type": "thinking", "text": chunk.text}
        except ChatError as exc:
            error = exc
        finally:
            chunks.close()
        result = _save_generated(
            prepared, settings, text="".join(parts),
            model=prepared.adapter.model_name, extra_warnings=notes, error=error,
        )
        saved = True
        yield {"type": "done", **result.as_dict()}
    except GeneratorExit:
        if not saved:
            _save_generated(
                prepared, settings, text="".join(parts),
                model=prepared.adapter.model_name, extra_warnings=notes,
                stopped=True,
            )
        raise


def _text_only(prepared: PreparedAnswer) -> list[ChatMessage]:
    return [*prepared.messages[:-1], ChatMessage(role="user", content=prepared.text_prompt)]


def _stream_generation(
    prepared: PreparedAnswer, settings: Settings, notes: list[str]
) -> Iterator[StreamChunk]:
    """Stream the reply; retry text-only if a vision prompt fails up front."""
    temperature = settings.generation.temperature
    produced = False
    first = stream_reply(prepared.adapter, prepared.messages, temperature=temperature)
    try:
        for chunk in first:
            produced = True
            yield chunk
        return
    except ChatError:
        if produced or not prepared.image_count:
            raise
    finally:
        first.close()
    notes.append(_VISION_FALLBACK)
    retry = stream_reply(prepared.adapter, _text_only(prepared), temperature=temperature)
    try:
        yield from retry
    finally:
        retry.close()


def _message_with_source_pages(
    text_prompt: str, sources: dict, settings: Settings
) -> tuple[ChatMessage, int]:
    parts: list[dict] = [{"type": "text", "text": text_prompt}]
    seen: set[tuple[int, int]] = set()
    count = 0
    for marker, hit in sources.items():
        if hit.page_number is None or Path(hit.path).suffix.lower() not in {
            ".pdf", ".pptx", ".ppt"
        }:
            continue
        key = (hit.document_id, hit.page_number)
        if key in seen:
            continue
        seen.add(key)
        try:
            png = render_page(hit.path, hit.page_number, settings)
        except Exception as exc:
            logger.warning("Could not render cited page %s: %s", marker, exc)
            continue
        parts.append({"type": "text", "text": f"Original page image for [{marker}]:"})
        parts.append(image_part(png))
        count += 1
        if count == 2:
            break
    if not count:
        return ChatMessage(role="user", content=text_prompt), 0
    return ChatMessage(role="user", content=parts), count


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
