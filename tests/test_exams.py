"""Phase 7 tests: past-paper extraction, concept frequency, mock exams."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.database.db import session_scope
from app.database.models import Chunk, Concept, Document
from app.exams.past_papers import (
    analyze_past_papers,
    link_concept,
    list_past_paper_questions,
    split_questions,
)
from app.generation.quizzes import generate_quiz
from app.ingestion.service import ingest
from app.models.chat import ChatResponse
from app.retrieval.indexing import index_embeddings


# ---- pure helpers ----

def test_split_questions_extracts_marks():
    text = (
        "Question 1. Explain reliability and validity. (10 marks)\n"
        "Question 2) Discuss informed consent in research ethics. (15 marks)\n"
    )
    qs = split_questions(text)
    assert len(qs) == 2
    assert qs[0]["number"] == "1" and qs[0]["marks"] == 10
    assert qs[1]["marks"] == 15


def test_link_concept_matches_known_names():
    names = ["Reliability", "Informed consent"]
    assert link_concept("Explain reliability here", names) == "Reliability"
    assert link_concept("about informed consent rules", names) == "Informed consent"
    assert link_concept("totally unrelated", names) == "General"


# ---- analysis against a synthetic past paper ----

@pytest.fixture
def past_paper(settings, db):
    with session_scope(settings) as s:
        # Pre-existing concepts to link against.
        s.add(Concept(course="REIT6811", name="Reliability"))
        s.add(Concept(course="REIT6811", name="Informed consent"))
        doc = Document(
            path="/v/REIT6811 Past Paper.pdf",
            title="REIT6811 Past Paper",
            course="REIT6811",
            document_type="past-paper",
            source_type="past-paper",
            trust_level=3,
            content_hash="abc",
        )
        s.add(doc)
        s.flush()
        s.add(
            Chunk(
                document_id=doc.id,
                chunk_index=0,
                content=(
                    "Question 1. Explain reliability of measurement. (10 marks)\n"
                    "Question 2. Discuss informed consent. (15 marks)\n"
                ),
                course="REIT6811",
                trust_level=3,
            )
        )
    return settings


def test_analyze_extracts_and_sets_frequency(past_paper):
    report = analyze_past_papers(course="REIT6811", settings=past_paper)
    assert report.documents == 1
    assert report.questions == 2

    with session_scope(past_paper) as s:
        concepts = {c.name: c.exam_frequency for c in s.query(Concept).all()}
    assert concepts.get("Reliability", 0) == 1
    assert concepts.get("Informed consent", 0) == 1

    listed = list_past_paper_questions(course="REIT6811", settings=past_paper)
    assert len(listed) == 2


def test_analyze_is_idempotent(past_paper):
    analyze_past_papers(course="REIT6811", settings=past_paper)
    analyze_past_papers(course="REIT6811", settings=past_paper)  # re-run
    listed = list_past_paper_questions(course="REIT6811", settings=past_paper)
    assert len(listed) == 2  # not doubled


# ---- mock exam generation ----

class StubExamAdapter:
    model_name = "stub-exam"

    def generate(self, messages, *, temperature=0.1, max_tokens=None):
        data = {
            "questions": [
                {
                    "type": "short", "question": "Critically discuss reliability.",
                    "answer": "consistency of measurement over repeated trials",
                    "concept": "Reliability", "difficulty": "hard",
                    "explanation": "Cover test-retest, internal consistency.",
                    "sources": ["S1"],
                }
            ]
        }
        return ChatResponse(content=json.dumps(data), model=self.model_name)


@pytest.fixture
def indexed(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    return settings


def test_mock_exam_generates_short_questions(indexed):
    res = generate_quiz(
        course="REIT6811", style="exam", settings=indexed, adapter=StubExamAdapter()
    )
    assert res.quiz_id
    assert res.questions
    assert all(q["type"] == "short" for q in res.questions)
    assert all("answer" not in q for q in res.questions)  # keys stay server-side
