"""Today page: deadlines CRUD, due reviews, weak topics, plan, and quiz-from-sources."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config.settings import get_settings
from app.database.db import session_scope
from app.database.models import Concept, ConceptProgress, LearningEvent, Quiz
from app.main import app


@pytest.fixture
def client(settings, db):
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _concept(settings, name, *, course="DECO7250", confidence=0.2, status="weak", due_in_days=None):
    now = datetime.now(timezone.utc)
    with session_scope(settings) as session:
        concept = Concept(course=course, name=name, exam_frequency=2)
        session.add(concept)
        session.flush()
        session.add(
            ConceptProgress(
                concept_id=concept.id,
                confidence=confidence,
                status=status,
                next_review=None if due_in_days is None else now + timedelta(days=due_in_days),
            )
        )
        return concept.id


def test_deadlines_crud_and_validation(client):
    today = date.today()
    soon = client.post(
        "/deadlines",
        json={"title": "  DECO7250   final ", "date": (today + timedelta(days=12)).isoformat(), "course": "deco 7250"},
    )
    assert soon.status_code == 200, soon.text
    assert soon.json()["title"] == "DECO7250 final"
    assert soon.json()["course"] == "DECO7250"
    assert soon.json()["days_until"] == 12
    past = client.post(
        "/deadlines",
        json={"title": "Old quiz", "date": (today - timedelta(days=3)).isoformat(), "kind": "weird"},
    ).json()
    assert past["kind"] == "other"
    assert client.post("/deadlines", json={"title": "  ", "date": today.isoformat()}).status_code == 422

    upcoming = client.get("/deadlines").json()["deadlines"]
    assert [d["title"] for d in upcoming] == ["DECO7250 final"]
    everything = client.get("/deadlines?include_past=true").json()["deadlines"]
    assert [d["title"] for d in everything] == ["Old quiz", "DECO7250 final"]

    assert client.delete(f"/deadlines/{past['id']}").status_code == 200
    assert client.delete(f"/deadlines/{past['id']}").status_code == 404


def test_today_summary(client, settings):
    today = date.today()
    client.post("/deadlines", json={"title": "Final", "date": (today + timedelta(days=9)).isoformat(), "course": "DECO7250"})
    client.post("/deadlines", json={"title": "Essay", "date": (today + timedelta(days=4)).isoformat(), "course": "REIT6811", "kind": "assignment"})
    _concept(settings, "Trust calibration", confidence=0.3, due_in_days=-1)
    _concept(settings, "Mental models", confidence=0.5, status="developing")
    _concept(settings, "Heuristics", confidence=0.9, status="strong", due_in_days=10)
    with session_scope(settings) as session:
        session.add(LearningEvent(course="DECO7250", event_type="correct", score=1, max_score=1))
        session.add(Quiz(course="DECO7250", submitted_at=datetime.now(timezone.utc), score=1, total=1))

    data = client.get("/today").json()
    assert [d["title"] for d in data["deadlines"]] == ["Essay", "Final"]
    assert [t["name"] for t in data["due"]] == ["Trust calibration"]
    assert data["due_count"] == 1
    assert [t["name"] for t in data["weak"]] == ["Mental models"]
    assert data["plan"]["exam_date"] == (today + timedelta(days=9)).isoformat()
    assert data["plan"]["days_until_exam"] == 9
    assert data["plan"]["blocks"]
    assert data["stats"] == {
        "concepts": 3,
        "average_confidence": round((0.3 + 0.5 + 0.9) / 3, 3),
        "answers_this_week": 1,
        "quizzes_this_week": 1,
    }

    scoped = client.get("/today?course=reit 6811").json()
    assert [d["title"] for d in scoped["deadlines"]] == ["Essay"]
    assert scoped["due"] == [] and scoped["stats"]["concepts"] == 0


def test_quiz_can_be_limited_to_answer_sources(settings, db, monkeypatch):
    from app.generation import quizzes
    from app.retrieval.service import SearchResponse

    seen = {}

    def fake_search(query, *, settings, flt, final_limit=None):
        seen["flt"] = flt
        seen["query"] = query
        return SearchResponse(query=query, hits=[], used_vector=False)

    monkeypatch.setattr(quizzes, "search", fake_search)
    result = quizzes.generate_quiz(
        course="DECO7250", topic="What is calibrated trust?", document_ids=[3, 5],
        num_questions=3, settings=settings,
    )
    assert sorted(seen["flt"].document_ids) == [3, 5]
    assert seen["flt"].course is None
    assert seen["query"] == "What is calibrated trust?"
    assert result.warnings  # no sources in this fake -> a clear warning, not a crash
