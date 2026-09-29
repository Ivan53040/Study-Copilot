"""Grounded Q&A agent: retrieve -> build context -> generate -> validate -> persist."""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from sqlalchemy import delete, func, select

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
    StreamCancel,
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
    created_conversation: bool = False  # this question started a new chat
    replaced: bool = False  # edit/regenerate: earlier messages were removed
    removed: list[dict] = field(default_factory=list)  # ...these, to undo it
    # Marks the saved question: SQLite can give a deleted message's id to the
    # next one, so the id alone can't tell whether it is still this question.
    turn: str = ""


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


def _truncate_from(session, conversation_id: int, message_id: int) -> list[dict]:
    """Drop a question and everything after it (to edit or regenerate it).

    Returns the removed messages, so the edit can be undone.
    """
    target = session.get(Message, message_id)
    if target is None or target.conversation_id != conversation_id or target.role != "user":
        raise ConversationEditError("That question is not part of this conversation.")
    removed = [
        {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "role": m.role,
            "content": m.content,
            "extra": m.extra,
            "created_at": m.created_at,
        }
        for m in session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id >= message_id)
            .order_by(Message.id)
        )
    ]
    session.execute(
        delete(Message).where(
            Message.conversation_id == conversation_id, Message.id >= message_id
        )
    )
    return removed


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
        existing = (
            session.get(Conversation, conversation_id) if conversation_id is not None else None
        )
        convo = existing or _get_or_create_conversation(session, None, convo_course)
        removed: list[dict] = []
        if replace_from_id is not None:
            removed = _truncate_from(session, convo.id, replace_from_id)
        history = _load_history(session, convo.id)
        turn = uuid.uuid4().hex
        user_message = Message(
            conversation_id=convo.id, role="user", content=question, extra={"turn": turn}
        )
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
            created_conversation=existing is None,
            replaced=replace_from_id is not None,
            removed=removed,
            turn=turn,
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
        message_id = None
        # The question can be gone (or already answered) if it was edited or
        # regenerated while this reply was still being written; the reply
        # then belongs to nothing.
        if _is_open_question(session, prepared):
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
) -> "AnswerStream":
    """Answer while the model writes, as a sequence of events.

    ``start`` (conversation, saved question id, sources) → ``thinking`` /
    ``delta`` pieces (``rethink`` when text already sent turns out to have been
    reasoning) → ``done`` (the saved answer, like :func:`answer`). Stopping or
    closing the stream early saves what was written so far.
    """
    return AnswerStream(
        question,
        settings or get_settings(),
        dict(
            adapter=adapter,
            course=course,
            scope_path=scope_path,
            study_set_id=study_set_id,
            context_mode=context_mode,
            context_items=context_items,
            conversation_id=conversation_id,
            note_path=note_path,
            replace_from_id=replace_from_id,
        ),
    )


class AnswerStream:
    """The events of one streamed answer (see :func:`stream_answer`).

    Iterate it for the events. When the reader presses Stop, :meth:`stop` may
    be called from another thread while the model is still working: it saves
    what was written so far at once, rather than whenever the model sends its
    next piece, so an edit or regenerate sent right after Stop can't be
    overtaken by the stopped answer. :meth:`close` ends the model request (it
    waits for a ``next()`` running in another thread to return first).
    """

    def __init__(self, question: str, settings: Settings, options: dict) -> None:
        self._question = question
        self._settings = settings
        self._options = options
        self._lock = threading.Lock()  # guards the state below
        self._step = threading.Lock()  # one next() / close() at a time
        self._prepared: PreparedAnswer | None = None
        self._parts: list[str] = []
        self._notes: list[str] = []
        self._stop_requested = False
        self._start_delivered = True
        self._finished = False  # the reply is saved (or the question undone)
        self._cancel = StreamCancel()  # ends the model request on stop()
        self._events = self._run()

    def __iter__(self) -> "AnswerStream":
        return self

    def __next__(self) -> dict:
        with self._step:
            return next(self._events)

    def close(self) -> None:
        with self._step:
            self._events.close()

    def stop(self, *, start_delivered: bool = True) -> None:
        """Save the answer so far now. ``start_delivered=False``: the reader
        never received ``start``, so the question is undone instead (an edit
        or regenerate puts back what it replaced), as if it was never sent."""
        with self._lock:
            if self._finished:
                return
            self._stop_requested = True
            self._start_delivered = start_delivered
            if self._prepared is not None:
                self._finish_stopped()
            # Still retrieving: _run finishes up as soon as that returns.
        # Outside the lock: the model request ends and the thread waiting on
        # it moves on (it finds the answer saved and stops).
        self._cancel.cancel()

    # -- internals (the caller holds self._lock where noted) -----------------

    def _finish_stopped(self) -> None:
        """Lock held. Save the partial answer, or undo an unseen question."""
        prepared = self._prepared
        assert prepared is not None
        self._finished = True
        if not self._start_delivered:
            _discard_question(prepared, self._settings)
        elif prepared.context.is_empty:
            _save_no_sources(prepared, self._settings)
        else:
            _save_generated(
                prepared, self._settings, text="".join(self._parts),
                model=prepared.adapter.model_name, extra_warnings=self._notes,
                stopped=True,
            )

    def _run(self) -> Iterator[dict]:
        prepared = prepare_answer(self._question, settings=self._settings, **self._options)
        with self._lock:
            self._prepared = prepared
            if self._stop_requested:  # stopped while retrieving
                self._start_delivered = False
                self._finish_stopped()
                return
        try:
            yield from self._answer(prepared)
        except GeneratorExit:
            with self._lock:
                if not self._finished:
                    self._finish_stopped()
            raise

    def _answer(self, prepared: PreparedAnswer) -> Iterator[dict]:
        settings = self._settings
        yield {
            "type": "start",
            "conversation_id": prepared.conversation_id,
            "user_message_id": prepared.user_message_id,
            "sources": prepared.source_dicts,
            "used_vector": prepared.used_vector,
            "model": prepared.adapter.model_name,
        }
        if prepared.context.is_empty:
            with self._lock:
                if self._finished:
                    return
                self._finished = True
                result = _save_no_sources(prepared, settings)
            yield {"type": "done", **result.as_dict()}
            return

        error: ChatError | None = None
        chunks = _stream_generation(prepared, settings, self._notes, self._cancel)
        try:
            for chunk in chunks:
                with self._lock:
                    if self._finished:  # stopped: already saved
                        return
                    if chunk.kind == "text":
                        self._parts.append(chunk.text)
                    elif chunk.kind == "rethink":
                        self._parts.clear()
                if chunk.kind == "text":
                    yield {"type": "delta", "text": chunk.text}
                elif chunk.kind == "rethink":
                    yield {"type": "rethink"}
                elif chunk.text:
                    yield {"type": "thinking", "text": chunk.text}
        except ChatError as exc:
            error = exc
        finally:
            chunks.close()
        with self._lock:
            if self._finished:
                return
            self._finished = True
            result = _save_generated(
                prepared, settings, text="".join(self._parts),
                model=prepared.adapter.model_name, extra_warnings=self._notes, error=error,
            )
        yield {"type": "done", **result.as_dict()}


def _is_open_question(session, prepared: PreparedAnswer) -> bool:
    """This answer's question is still saved and is the chat's last message."""
    question = session.get(Message, prepared.user_message_id)
    if question is None or (question.extra or {}).get("turn") != prepared.turn:
        return False
    latest = session.scalar(
        select(func.max(Message.id)).where(Message.conversation_id == prepared.conversation_id)
    )
    return latest == question.id


def _discard_question(prepared: PreparedAnswer, settings: Settings) -> None:
    """Undo a question nobody saw an answer start for: delete it, put back the
    messages an edit or regenerate removed, and drop a chat it created."""
    with session_scope(settings) as session:
        if not _is_open_question(session, prepared):
            return
        session.execute(delete(Message).where(Message.id == prepared.user_message_id))
        session.flush()
        for row in prepared.removed:
            session.add(Message(**row))
        if prepared.created_conversation:
            left = session.scalar(
                select(func.count(Message.id)).where(
                    Message.conversation_id == prepared.conversation_id
                )
            )
            convo = session.get(Conversation, prepared.conversation_id)
            if not left and convo is not None:
                session.delete(convo)


def _text_only(prepared: PreparedAnswer) -> list[ChatMessage]:
    return [*prepared.messages[:-1], ChatMessage(role="user", content=prepared.text_prompt)]


def _stream_generation(
    prepared: PreparedAnswer,
    settings: Settings,
    notes: list[str],
    cancel: StreamCancel | None = None,
) -> Iterator[StreamChunk]:
    """Stream the reply; retry text-only if a vision prompt fails up front."""
    temperature = settings.generation.temperature
    produced = False
    first = stream_reply(
        prepared.adapter, prepared.messages, temperature=temperature, cancel=cancel
    )
    try:
        for chunk in first:
            produced = True
            yield chunk
        return
    except ChatError:
        if produced or not prepared.image_count or (cancel is not None and cancel.cancelled):
            raise
    finally:
        first.close()
    notes.append(_VISION_FALLBACK)
    retry = stream_reply(
        prepared.adapter, _text_only(prepared), temperature=temperature, cancel=cancel
    )
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
