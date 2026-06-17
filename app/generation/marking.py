"""Grade quiz submissions and fold results into learning history."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.prompts import GRADE_SYSTEM_PROMPT, build_grade_prompt
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Quiz, QuizQuestion
from app.generation.jsonparse import extract_json
from app.learning.service import Outcome, record_outcomes
from app.models.chat import ChatAdapter, ChatError, ChatMessage, get_chat_adapter

_OUTCOME_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}
_WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class GradedQuestion:
    question_id: int
    concept: str | None
    your_answer: str
    correct_answer: str
    outcome: str
    score: float
    explanation: str | None
    feedback: str | None = None


def _norm(s: str) -> str:
    return " ".join(_WORD_RE.findall(s.lower()))


def grade_mcq(answer_key: str, submitted: str, options: list[str] | None) -> str:
    submitted = (submitted or "").strip()
    if _norm(submitted) == _norm(answer_key):
        return "correct"
    # Accept a letter (A/B/C/D) or a 1-based index referring to the option.
    if options:
        idx = None
        if len(submitted) == 1 and submitted.upper().isalpha():
            idx = ord(submitted.upper()) - ord("A")
        elif submitted.isdigit():
            idx = int(submitted) - 1
        if idx is not None and 0 <= idx < len(options):
            if _norm(options[idx]) == _norm(answer_key):
                return "correct"
    return "incorrect"


def _heuristic_short(model_answer: str, submitted: str) -> str:
    expected = set(_WORD_RE.findall(model_answer.lower()))
    got = set(_WORD_RE.findall(submitted.lower()))
    if not submitted.strip():
        return "incorrect"
    if not expected:
        return "partial"
    overlap = len(expected & got) / len(expected)
    if overlap >= 0.6:
        return "correct"
    if overlap >= 0.3:
        return "partial"
    return "incorrect"


def grade_short(
    question: str,
    model_answer: str,
    submitted: str,
    adapter: ChatAdapter,
    *,
    settings: Settings,
) -> tuple[str, str | None]:
    """Return (outcome, feedback). Falls back to a heuristic if no model."""
    if not submitted.strip():
        return "incorrect", "No answer provided."
    try:
        resp = adapter.generate(
            [
                ChatMessage(role="system", content=GRADE_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=build_grade_prompt(question, model_answer, submitted),
                ),
            ],
            temperature=0.0,
        )
        data = extract_json(resp.content)
        verdict = str(data.get("verdict", "")).lower()
        if verdict in _OUTCOME_SCORE:
            return verdict, data.get("feedback")
    except (ChatError, ValueError, AttributeError):
        pass
    return _heuristic_short(model_answer, submitted), "Graded offline (heuristic)."


def submit_quiz(
    quiz_id: int,
    answers: dict[int, str],
    *,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
) -> dict:
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings)

    with session_scope(settings) as session:
        quiz = session.get(Quiz, quiz_id)
        if quiz is None:
            raise KeyError(f"Quiz {quiz_id} not found")
        questions = session.scalars(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id)
        ).all()

        graded: list[GradedQuestion] = []
        outcomes: list[Outcome] = []
        for q in questions:
            submitted = (answers.get(q.id) or "").strip()
            if q.type == "mcq":
                outcome = grade_mcq(q.answer_key, submitted, q.options)
                feedback = None
            else:
                outcome, feedback = grade_short(
                    q.question, q.answer_key, submitted, adapter, settings=settings
                )
            score = _OUTCOME_SCORE[outcome]
            graded.append(
                GradedQuestion(
                    question_id=q.id,
                    concept=q.concept_name,
                    your_answer=submitted,
                    correct_answer=q.answer_key,
                    outcome=outcome,
                    score=score,
                    explanation=q.explanation,
                    feedback=feedback,
                )
            )
            outcomes.append(
                Outcome(
                    concept_id=q.concept_id,
                    course=quiz.course,
                    event_type=outcome,
                    score=score,
                    max_score=1.0,
                    difficulty=q.difficulty,
                    source_reference=f"quiz:{quiz_id}",
                    quiz_question_id=q.id,
                )
            )

        progress = record_outcomes(session, outcomes)

        total = float(len(graded))
        scored = sum(g.score for g in graded)
        quiz.score = scored
        quiz.total = total
        quiz.submitted_at = datetime.now(timezone.utc)

        return {
            "quiz_id": quiz_id,
            "score": scored,
            "total": total,
            "results": [
                {
                    "question_id": g.question_id,
                    "concept": g.concept,
                    "your_answer": g.your_answer,
                    "correct_answer": g.correct_answer,
                    "outcome": g.outcome,
                    "score": g.score,
                    "explanation": g.explanation,
                    "feedback": g.feedback,
                }
                for g in graded
            ],
            "progress": progress,
        }
