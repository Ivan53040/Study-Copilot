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

    def fake_stream(url, *, json, headers, timeout, cancel=None):
        sent.update(json=json, url=url)
        return _FakeStream(lines)

    monkeypatch.setattr(chat_models, "_open_stream", fake_stream)
    adapter = LMStudioChatAdapter("http://x/v1", "m")
    chunks = list(adapter.stream([chat_models.ChatMessage("user", "q")]))
    assert sent["json"]["stream"] is True
    assert "".join(c.text for c in chunks if c.kind == "thinking") == "Think about it."
    assert "".join(c.text for c in chunks if c.kind == "text") == "Reliability is consistency [S1]."


def test_openai_stream_accepts_non_streaming_server(monkeypatch):
    body = {"choices": [{"message": {"content": "Plain answer"}}]}
    monkeypatch.setattr(
        chat_models,
        "_open_stream",
        lambda *a, **k: _FakeStream([json.dumps(body)], content_type="application/json"),
    )
    chunks = list(LMStudioChatAdapter("http://x/v1", "m").stream([]))
    assert [(c.kind, c.text) for c in chunks] == [("text", "Plain answer")]


def test_openai_stream_http_error_is_chat_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(chat_models, "_open_stream", boom)
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


# ---- Stop while the model is busy -----------------------------------------


class _Gated:
    """A model that sends nothing until ``release`` is set (a slow prompt)."""

    model_name = "gated"

    def __init__(self, pieces=("Late words [S1].",)):
        import threading

        self.release = threading.Event()
        self.pieces = pieces
        self.closed = False

    def stream(self, messages, *, temperature=0.1):
        try:
            self.release.wait(timeout=10)
            for piece in self.pieces:
                yield StreamChunk("text", piece)
        finally:
            self.closed = True


def _in_thread(fn):
    import threading

    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - surfaced by the test
            box["error"] = exc

    thread = threading.Thread(target=run)
    thread.start()
    return thread, box


def test_stop_saves_at_once_and_is_not_overtaken_by_regenerate(indexed):
    model = _Gated()
    events = stream_answer("What is reliability?", settings=indexed, adapter=model)
    start = next(events)
    # The reader's next() is stuck waiting for the model's first piece.
    waiting, _ = _in_thread(lambda: next(events, None))
    events.stop()  # Stop pressed: saved now, not when the model speaks
    rows = _messages(indexed, start["conversation_id"])
    assert [r[1] for r in rows] == ["user", "assistant"]
    assert any("Stopped" in w for w in rows[1][3]["warnings"])

    # Regenerate right away replaces the question and the stopped answer.
    again = answer(
        "What is reliability?", settings=indexed, adapter=EchoChatAdapter(),
        conversation_id=start["conversation_id"], replace_from_id=start["user_message_id"],
    )
    # Now the slow model finally sends its words: nothing more is saved.
    model.release.set()
    waiting.join(timeout=10)
    events.close()
    assert model.closed
    rows = _messages(indexed, start["conversation_id"])
    assert [r[0] for r in rows] == [again.user_message_id, again.message_id]
    assert "Late words" not in rows[1][2]


def test_stop_before_start_undoes_a_new_question(indexed):
    import threading

    from app.agent import study_agent

    entered, go_on = threading.Event(), threading.Event()
    real_prepare = study_agent.prepare_answer

    def slow_prepare(*args, **kwargs):
        prepared = real_prepare(*args, **kwargs)
        entered.set()
        go_on.wait(timeout=10)
        return prepared

    study_agent.prepare_answer = slow_prepare
    try:
        events = stream_answer("What is reliability?", settings=indexed, adapter=EchoChatAdapter())
        waiting, box = _in_thread(lambda: next(events, None))
        assert entered.wait(timeout=10)
        events.stop(start_delivered=False)  # Stop while still retrieving
        go_on.set()
        waiting.join(timeout=10)
        events.close()
    finally:
        study_agent.prepare_answer = real_prepare
    assert box.get("value") is None  # the reader never gets ``start``
    with session_scope(indexed) as session:
        assert session.query(Message).count() == 0
        from app.database.models import Conversation

        assert session.query(Conversation).count() == 0


def test_stop_before_start_in_an_edit_puts_the_old_turn_back(indexed):
    first = answer("reliability", settings=indexed, adapter=EchoChatAdapter())
    before = _messages(indexed, first.conversation_id)
    events = stream_answer(
        "What is validity?", settings=indexed, adapter=_Gated(),
        conversation_id=first.conversation_id, replace_from_id=first.user_message_id,
    )
    next(events)  # (produced, but the reader never received it)
    events.stop(start_delivered=False)
    events.close()
    # As if the edit was never sent: the original question and answer are back.
    assert _messages(indexed, first.conversation_id) == before


def test_a_reply_whose_question_was_replaced_is_not_saved(indexed):
    model = _Gated()
    events = stream_answer("What is reliability?", settings=indexed, adapter=model)
    start = next(events)
    # Another window edits the question while this answer is being written.
    answer(
        "Define reliability", settings=indexed, adapter=EchoChatAdapter(),
        conversation_id=start["conversation_id"], replace_from_id=start["user_message_id"],
    )
    model.release.set()
    done = list(events)[-1]
    assert done["type"] == "done" and done["message_id"] is None
    rows = _messages(indexed, start["conversation_id"])
    assert [r[2] for r in rows][0] == "Define reliability"
    assert "Late words" not in " ".join(r[2] for r in rows)


async def test_http_relay_stops_the_stream_when_the_reader_leaves(indexed):
    import anyio

    from app.api.chat import _ndjson

    model = _Gated()
    events = stream_answer("What is reliability?", settings=indexed, adapter=model)
    relay = _ndjson(events)
    first = json.loads(await relay.__anext__())
    assert first["type"] == "start"
    with anyio.move_on_after(0.3):  # the model is silent; the reader leaves
        await relay.__anext__()
    await relay.aclose()  # runs the relay's cleanup: stop() then close()
    rows = _messages(indexed, first["conversation_id"])
    assert [r[1] for r in rows] == ["user", "assistant"]
    assert any("Stopped" in w for w in rows[1][3]["warnings"])
    model.release.set()


# ---- reasoning opened in the prompt ----------------------------------------


def test_closing_think_tag_alone_turns_earlier_text_into_thinking(indexed):
    class OnlyCloses:
        model_name = "closes"

        def stream(self, messages, *, temperature=0.1):
            yield from (
                StreamChunk("text", t)
                for t in ["The user asks about ", "reliability.</thi", "nk>\n\nReliability is consistency [S1]."]
            )

    chunks = list(stream_reply(OnlyCloses(), []))
    kinds = [c.kind for c in chunks]
    assert "rethink" in kinds
    after = kinds.index("rethink")
    # Everything passed on before the rethink was reasoning; after it, the answer.
    assert "".join(c.text for c in chunks[:after]) == "The user asks about reliability."
    assert "".join(c.text for c in chunks[after:] if c.kind == "text").strip() == "Reliability is consistency [S1]."

    events = list(stream_answer("What is reliability?", settings=indexed, adapter=OnlyCloses()))
    assert {"type": "rethink"} in events
    done = events[-1]
    assert done["answer"] == "Reliability is consistency [S1]."


def test_stop_ends_the_model_request_while_it_reads_the_prompt(indexed):
    """A local model reading a long prompt sends nothing for a while; Stop
    must not wait for it (it would keep the model busy and delay the next
    question)."""
    import socket
    import threading
    import time

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    seen: dict = {}

    def silent_model():
        conn, _ = server.accept()
        conn.settimeout(10)
        try:
            # Read the whole request, then send nothing and wait: recv()
            # returns b"" once the client hangs up.
            while conn.recv(65536):
                pass
            seen["closed"] = True
        except OSError:
            seen["closed"] = True
        conn.close()

    threading.Thread(target=silent_model, daemon=True).start()
    adapter = LMStudioChatAdapter(f"http://127.0.0.1:{port}/v1", "slow", timeout=30)
    events = stream_answer("What is reliability?", settings=indexed, adapter=adapter)
    start = next(events)
    waiting, box = _in_thread(lambda: next(events, None))
    time.sleep(0.3)  # the request is out; the model is "thinking"
    began = time.monotonic()
    events.stop()
    waiting.join(timeout=5)
    assert not waiting.is_alive() and time.monotonic() - began < 3
    assert box.get("value") is None and "error" not in box
    events.close()
    time.sleep(0.2)
    assert seen.get("closed") is True
    rows = _messages(indexed, start["conversation_id"])
    assert [r[1] for r in rows] == ["user", "assistant"]
    server.close()
