"""Phase 5 tests: confidence, spaced repetition, marking, quiz e2e, progress."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.generation.marking import _heuristic_short, grade_mcq, submit_quiz
from app.generation.quizzes import generate_quiz
from app.ingestion.service import ingest
from app.learning.confidence import EventLike, compute_confidence, status_band
from app.learning.service import get_progress
from app.learning.spaced_repetition import next_interval_days
from app.models.chat import ChatResponse
from app.retrieval.indexing import index_embeddings


# ---- confidence ----

def _ev(score, max_score=1.0, diff="medium", days_ago=0):
    return EventLike(
        score, max_score, diff,
        datetime.now(timezone.utc) - timedelta(days=days_ago),
    )


def test_confidence_empty_is_zero():
    conf, ev = compute_confidence([])
    assert conf == 0.0 and ev["events"] == 0


def test_confidence_high_when_all_correct_recent():
    conf, _ = compute_confidence([_ev(1.0) for _ in range(5)])
    assert conf >= 0.85
    assert status_band(conf) == "strong"


def test_confidence_low_when_all_wrong():
    conf, _ = compute_confidence([_ev(0.0) for _ in range(5)])
    assert conf < 0.40
    assert status_band(conf) == "weak"


def test_status_bands():
    assert status_band(0.9) == "strong"
    assert status_band(0.75) == "good"
    assert status_band(0.5) == "developing"
    assert status_band(0.1) == "weak"


# ---- spaced repetition ----

def test_spaced_repetition_intervals():
    assert next_interval_days("incorrect", 0.9) == 1
    assert next_interval_days("partial", 0.9) == 3
    assert next_interval_days("correct", 0.5) == 7
    assert next_interval_days("correct", 0.8) == 14
    assert next_interval_days("correct", 0.95) == 30


# ---- marking ----

def test_grade_mcq_exact_letter_and_index():
    opts = ["alpha", "beta", "gamma", "delta"]
    assert grade_mcq("beta", "beta", opts) == "correct"
    assert grade_mcq("beta", "B", opts) == "correct"   # letter
    assert grade_mcq("beta", "2", opts) == "correct"   # 1-based index
    assert grade_mcq("beta", "gamma", opts) == "incorrect"


def test_heuristic_short_grading():
    expected = "reliability is the consistency of measurement"
    assert _heuristic_short(expected, "consistency of measurement reliability") == "correct"
    assert _heuristic_short(expected, "consistency measurement") == "partial"
    assert _heuristic_short(expected, "banana") == "incorrect"
    assert _heuristic_short(expected, "") == "incorrect"


# ---- quiz end-to-end ----

class StubQuizAdapter:
    model_name = "stub"

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        quiz = {
            "questions": [
                {
                    "type": "mcq", "question": "What is reliability?",
                    "options": ["consistency", "accuracy", "bias", "sampling"],
                    "answer": "consistency", "concept": "Reliability",
                    "difficulty": "easy", "explanation": "Reliability = consistency.",
                    "sources": ["S1"],
                },
                {
                    "type": "short", "question": "Define validity.",
                    "answer": "measures what it intends to measure",
                    "concept": "Validity", "difficulty": "hard",
                    "explanation": "Validity is about measuring the intended thing.",
                    "sources": ["S2"],
                },
            ]
        }
        return ChatResponse(content=json.dumps(quiz), model=self.model_name)


@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_generate_quiz_persists_without_answer_keys(indexed):
    res = generate_quiz(
        course="REIT6811", week=1, settings=indexed, adapter=StubQuizAdapter()
    )
    assert res.quiz_id
    assert len(res.questions) == 2
    # Client questions must NOT leak answer keys.
    assert all("answer" not in q and "answer_key" not in q for q in res.questions)
    assert res.questions[0]["type"] == "mcq"


def test_submit_quiz_marks_and_updates_progress(indexed):
    res = generate_quiz(
        course="REIT6811", settings=indexed, adapter=StubQuizAdapter()
    )
    qmap = {q["concept"]: q["id"] for q in res.questions}
    from app.models.chat import EchoChatAdapter

    submission = submit_quiz(
        res.quiz_id,
        {
            qmap["Reliability"]: "consistency",  # correct mcq
            qmap["Validity"]: "it measures what it intends to measure",  # correct short
        },
        settings=indexed,
        adapter=EchoChatAdapter(),
    )
    assert submission["total"] == 2.0
    assert submission["score"] == 2.0
    assert len(submission["results"]) == 2
    # Correct answers now revealed in results.
    assert all(r["correct_answer"] for r in submission["results"])
    # Progress updated for both concepts with positive confidence.
    assert submission["progress"]
    assert all(p["confidence"] > 0 for p in submission["progress"].values())


def test_progress_endpoint_data_after_submit(indexed):
    res = generate_quiz(
        course="REIT6811", settings=indexed, adapter=StubQuizAdapter()
    )
    qmap = {q["concept"]: q["id"] for q in res.questions}
    submit_quiz(
        res.quiz_id,
        {qmap["Reliability"]: "wrong", qmap["Validity"]: ""},  # both wrong
        settings=indexed,
        adapter=__import__("app.models.chat", fromlist=["EchoChatAdapter"]).EchoChatAdapter(),
    )
    from app.database.db import session_scope

    with session_scope(indexed) as s:
        rows = get_progress(s, course="REIT6811")
    names = {r["name"] for r in rows}
    assert {"Reliability", "Validity"} <= names
    # Both answered wrong -> weak status.
    assert all(r["status"] == "weak" for r in rows if r["name"] in {"Reliability", "Validity"})
