"""Streaming answers, stop/partial save, edit/regenerate and note-scoped chat."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.study_agent import ConversationEditError, answer, stream_answer
from app.config.settings import get_settings
from app.database.db import session_scope
from app.database.models import Message
from app.ingestion.service import ingest
from app.main import app
from app.models import chat as chat_models
from app.models.chat import (
    ChatResponse,
    EchoChatAdapter,
    LMStudioChatAdapter,
    StreamChunk,
    stream_reply,
    strip_think,
)
from app.retrieval.indexing import index_embeddings

NOTE = "REIT6811 - Research Methods/REIT6811_Week1_Revision_Notes.md"


@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def _messages(settings, conversation_id):
    with session_scope(settings) as session:
        rows = (
            session.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.id)
            .all()
        )
        return [(m.id, m.role, m.content, m.extra) for m in rows]


# ---- think handling -------------------------------------------------------


def test_strip_think_removes_reasoning():
    assert strip_think("<think>plan it</think>\n\nReliability [S1]") == "Reliability [S1]"
    assert strip_think("plan it</think>Answer") == "Answer"
    assert strip_think("No reasoning here.") == "No reasoning here."


def test_stream_reply_splits_inline_think_across_deltas():
    class Split:
        model_name = "split"

        def stream(self, messages, *, temperature=0.1):
            yield from (StreamChunk("text", t) for t in ["<thi", "nk>why", "</th", "ink>Hi <b>", "x</b>"])

    chunks = list(stream_reply(Split(), []))
    assert "".join(c.text for c in chunks if c.kind == "thinking") == "why"
    assert "".join(c.text for c in chunks if c.kind == "text") == "Hi <b>x</b>"


def test_stream_reply_falls_back_to_generate():
    class GenerateOnly:
        model_name = "g"

        def generate(self, messages, *, temperature=0.1):
            return ChatResponse(content="whole answer", model="g")

    assert [c.text for c in stream_reply(GenerateOnly(), [])] == ["whole answer"]


class _FakeStream:
    def __init__(self, lines, content_type="text/event-stream", status=200):
        self._lines = lines
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.text = ""
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def read(self):
        return "\n".join(self._lines).encode()

    def iter_lines(self):
        yield from self._lines


def test_openai_stream_parses_sse_and_reasoning(monkeypatch):
    sent = {}
    events = [
        {"choices": [{"delta": {"reasoning_content": "Think about "}}]},
        {"choices": [{"delta": {"reasoning_content": "it."}}]},
        {"choices": [{"delta": {"content": "Reliability "}}]},
        {"choices": [{"delta": {"content": "is consistency [S1]."}}]},
    ]
    lines = [f"data: {json.dumps(e)}" for e in events] + ["", ": keep-alive", "data: [DONE]"]

    def fake_stream(method, url, *, json, headers, timeout):
        sent.update(json=json, url=url)
        return _FakeStream(lines)

    monkeypatch.setattr(chat_models.httpx, "stream", fake_stream)
    adapter = LMStudioChatAdapter("http://x/v1", "m")
    chunks = list(adapter.stream([chat_models.ChatMessage("user", "q")]))
    assert sent["json"]["stream"] is True
    assert "".join(c.text for c in chunks if c.kind == "thinking") == "Think about it."
    assert "".join(c.text for c in chunks if c.kind == "text") == "Reliability is consistency [S1]."


def test_openai_stream_accepts_non_streaming_server(monkeypatch):
    body = {"choices": [{"message": {"content": "Plain answer"}}]}
    monkeypatch.setattr(
        chat_models.httpx,
        "stream",
        lambda *a, **k: _FakeStream([json.dumps(body)], content_type="application/json"),
    )
    chunks = list(LMStudioChatAdapter("http://x/v1", "m").stream([]))
    assert [(c.kind, c.text) for c in chunks] == [("text", "Plain answer")]


def test_openai_stream_http_error_is_chat_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(chat_models.httpx, "stream", boom)
    with pytest.raises(chat_models.ChatError):
        list(LMStudioChatAdapter("http://x/v1", "m").stream([]))


# ---- streamed answers ------------------------------------------------------


def test_stream_answer_events_and_saved_reply(indexed):
    events = list(stream_answer("What is reliability?", settings=indexed, adapter=EchoChatAdapter()))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert kinds.count("delta") > 1
    start, done = events[0], events[-1]
    assert start["sources"] and start["user_message_id"]
    streamed = "".join(e["text"] for e in events if e["type"] == "delta")
    assert done["answer"] == streamed.strip()
    assert done["citations"] and "[S1]" in done["answer"]
    rows = _messages(indexed, done["conversation_id"])
    assert [r[1] for r in rows] == ["user", "assistant"]
    assert rows[0][0] == start["user_message_id"] == done["user_message_id"]
    assert rows[1][0] == done["message_id"]


def test_stopping_a_stream_saves_the_partial_answer(indexed):
    events = stream_answer("What is reliability?", settings=indexed, adapter=EchoChatAdapter())
    start = next(events)
    first = next(events)
    assert first["type"] == "delta"
    events.close()  # the reader pressed Stop / went away
    rows = _messages(indexed, start["conversation_id"])
    assert [r[1] for r in rows] == ["user", "assistant"]
    assert rows[1][2] == first["text"].strip()
    assert any("Stopped" in w for w in rows[1][3]["warnings"])
    # A partial answer is not flagged for missing citations.
    assert not any("without citing" in w for w in rows[1][3]["warnings"])


def test_model_down_while_streaming_keeps_sources(indexed):
    class Down:
        model_name = "down"

        def stream(self, messages, *, temperature=0.1):
            raise chat_models.ChatError("connection refused")
            yield  # pragma: no cover

    events = list(stream_answer("reliability", settings=indexed, adapter=Down()))
    done = events[-1]
    assert done["type"] == "done"
    assert "unavailable" in done["answer"]
    assert done["sources"]
    assert any("Chat model unavailable" in w for w in done["warnings"])


# ---- edit / regenerate -----------------------------------------------------


def test_regenerate_replaces_the_question_and_later_replies(indexed):
    first = answer("reliability", settings=indexed, adapter=EchoChatAdapter())
    second = answer(
        "and validity?", settings=indexed, adapter=EchoChatAdapter(),
        conversation_id=first.conversation_id,
    )
    # Edit the first question: it and everything after it are replaced.
    edited = answer(
        "What is validity?", settings=indexed, adapter=EchoChatAdapter(),
        conversation_id=first.conversation_id, replace_from_id=first.user_message_id,
    )
    rows = _messages(indexed, first.conversation_id)
    assert [(r[1], r[2]) for r in rows][0] == ("user", "What is validity?")
    assert len(rows) == 2
    assert second.user_message_id not in [r[0] for r in rows]
    assert edited.message_id == rows[1][0]


def test_replace_from_must_be_a_question_in_the_conversation(indexed):
    first = answer("reliability", settings=indexed, adapter=EchoChatAdapter())
    other = answer("validity", settings=indexed, adapter=EchoChatAdapter())
    with pytest.raises(ConversationEditError):
        answer(
            "x", settings=indexed, adapter=EchoChatAdapter(),
            conversation_id=first.conversation_id, replace_from_id=other.user_message_id,
        )
    with pytest.raises(ConversationEditError):
        answer(
            "x", settings=indexed, adapter=EchoChatAdapter(),
            conversation_id=first.conversation_id, replace_from_id=first.message_id,
        )
    # Nothing was deleted by the rejected edits.
    assert len(_messages(indexed, first.conversation_id)) == 2


def test_history_is_not_duplicated_in_the_prompt(indexed):
    seen: list = []

    class Spy(EchoChatAdapter):
        def generate(self, messages, *, temperature=0.1, max_tokens=None):
            seen.append(messages)
            return super().generate(messages, temperature=temperature)

    first = answer("reliability", settings=indexed, adapter=Spy())
    answer("validity", settings=indexed, adapter=Spy(), conversation_id=first.conversation_id)
    prompt = seen[-1]
    roles = [m.role for m in prompt]
    assert roles == ["system", "user", "assistant", "user"]
    assert "QUESTION: validity" in prompt[-1].content


# ---- note-scoped chat ------------------------------------------------------


def test_note_scope_answers_from_the_open_note(indexed):
    res = answer("What is validity?", settings=indexed, adapter=EchoChatAdapter(), note_path=NOTE)
    assert res.sources
    assert res.sources[0]["path"].replace("\\", "/").endswith(NOTE)
    assert all(s["path"].replace("\\", "/").endswith(NOTE) for s in res.sources)
    assert "[S1]" in res.answer


def test_note_scope_missing_note(indexed):
    with pytest.raises(FileNotFoundError):
        answer("x", settings=indexed, adapter=EchoChatAdapter(), note_path="REIT6811 - Research Methods/nope.md")


# ---- HTTP ------------------------------------------------------------------


@pytest.fixture
def client(indexed):
    indexed.models.default_provider = "echo"
    app.dependency_overrides[get_settings] = lambda: indexed
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _ndjson(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


def test_http_stream_and_message_ids(client):
    res = client.post("/chat/stream", json={"message": "What is reliability?"})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/x-ndjson")
    events = _ndjson(res)
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"
    done = events[-1]

    detail = client.get(f"/conversations/{done['conversation_id']}").json()
    assert [m["id"] for m in detail["messages"]] == [done["user_message_id"], done["message_id"]]

    again = client.post(
        "/chat/stream",
        json={
            "message": "Define reliability",
            "conversation_id": done["conversation_id"],
            "replace_from_id": done["user_message_id"],
        },
    )
    assert _ndjson(again)[-1]["type"] == "done"
    detail = client.get(f"/conversations/{done['conversation_id']}").json()
    assert [m["content"] for m in detail["messages"]][0] == "Define reliability"
    assert len(detail["messages"]) == 2


def test_http_errors(client):
    bad = client.post("/chat/stream", json={"message": "x", "note_path": "REIT6811 - Research Methods/nope.md"})
    events = _ndjson(bad)
    assert events == [{"type": "error", "message": events[0]["message"]}]
    assert "not found" in events[0]["message"].lower()

    res = client.post("/chat", json={"message": "x", "note_path": "REIT6811 - Research Methods/nope.md"})
    assert res.status_code == 404
    res = client.post("/chat", json={"message": "x", "conversation_id": 1, "replace_from_id": 999})
    assert res.status_code == 400
