"""Conversation history endpoints used by the sidebar Recents list."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.database.db import session_scope
from app.database.models import Conversation, Message
from app.main import app


@pytest.fixture
def client(settings, db):
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _seed(settings, *, course=None, title=None, user_text="What is reliability?", minutes_ago=0):
    at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    with session_scope(settings) as session:
        convo = Conversation(course=course, title=title, created_at=at)
        session.add(convo)
        session.flush()
        session.add(Message(conversation_id=convo.id, role="user", content=user_text, created_at=at))
        session.add(
            Message(
                conversation_id=convo.id,
                role="assistant",
                content="Consistency of measurement [S1].",
                extra={"citations": [], "warnings": []},
                created_at=at + timedelta(seconds=5),
            )
        )
        return convo.id


def test_list_conversations_newest_first_with_auto_titles(client, settings):
    older = _seed(settings, user_text="Explain   validity\nplease", minutes_ago=30)
    newer = _seed(settings, course="REIT6811", user_text="x" * 200, minutes_ago=1)
    # A conversation with no messages yet is not listed.
    with session_scope(settings) as session:
        session.add(Conversation())

    res = client.get("/conversations")
    assert res.status_code == 200, res.text
    rows = res.json()["conversations"]
    assert [row["id"] for row in rows] == [newer, older]
    assert rows[1]["title"] == "Explain validity please"
    assert rows[0]["title"].endswith("…") and len(rows[0]["title"]) == 80
    assert rows[0]["course"] == "REIT6811"
    assert rows[0]["message_count"] == 2
    assert rows[0]["updated_at"].endswith("+00:00")


def test_rename_and_revert_conversation_title(client, settings):
    cid = _seed(settings)
    res = client.patch(f"/conversations/{cid}", json={"title": "  Exam   prep  "})
    assert res.status_code == 200
    assert res.json()["title"] == "Exam prep"
    row = client.get("/conversations").json()["conversations"][0]
    assert row["title"] == "Exam prep" and row["custom_title"] is True

    client.patch(f"/conversations/{cid}", json={"title": ""})
    row = client.get("/conversations").json()["conversations"][0]
    assert row["title"] == "What is reliability?" and row["custom_title"] is False
    assert client.get(f"/conversations/{cid}").json()["title"] == "What is reliability?"


def test_delete_conversation_removes_messages(client, settings):
    cid = _seed(settings)
    assert client.delete(f"/conversations/{cid}").json() == {"deleted": cid}
    assert client.get(f"/conversations/{cid}").status_code == 404
    assert client.get("/conversations").json()["conversations"] == []
    with session_scope(settings) as session:
        assert session.query(Message).filter(Message.conversation_id == cid).count() == 0


def test_missing_conversation_returns_404(client):
    assert client.patch("/conversations/999", json={"title": "x"}).status_code == 404
    assert client.delete("/conversations/999").status_code == 404


def test_detail_returns_extra_and_offset_timestamps(client, settings):
    cid = _seed(settings)
    detail = client.get(f"/conversations/{cid}").json()
    assert detail["title"] == "What is reliability?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["extra"] == {"citations": [], "warnings": []}
    assert all(m["created_at"].endswith("+00:00") for m in detail["messages"])


def test_conversation_without_user_text_gets_placeholder_title(client, settings):
    with session_scope(settings) as session:
        convo = Conversation()
        session.add(convo)
        session.flush()
        session.add(Message(conversation_id=convo.id, role="assistant", content="Hello"))
    row = client.get("/conversations").json()["conversations"][0]
    assert row["title"] == "Untitled chat"


def test_list_limit_is_clamped(client, settings):
    for i in range(3):
        _seed(settings, user_text=f"q{i}", minutes_ago=i)
    assert len(client.get("/conversations?limit=0").json()["conversations"]) == 1
    assert len(client.get("/conversations?limit=2").json()["conversations"]) == 2
