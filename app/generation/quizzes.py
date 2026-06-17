"""Generate quizzes from retrieved sources and persist them."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.context import build_context
from app.agent.prompts import QUIZ_SYSTEM_PROMPT, build_quiz_prompt
from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Quiz, QuizQuestion
from app.generation.jsonparse import extract_json
from app.learning.concepts import get_or_create_concept
from app.logging_config import get_logger
from app.models.chat import ChatAdapter, ChatError, ChatMessage, get_chat_adapter
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter

logger = get_logger("generation.quiz")

_VALID_TYPES = {"mcq", "short"}
_VALID_DIFF = {"easy", "medium", "hard"}


@dataclass
class QuizResult:
    quiz_id: int | None
    course: str | None
    week: int | None
    topic: str | None
    # Client-facing questions (NO answer keys).
    questions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "quiz_id": self.quiz_id,
            "course": self.course,
            "week": self.week,
            "topic": self.topic,
            "questions": self.questions,
            "warnings": self.warnings,
        }


def _scope(course: str | None, week: int | None, topic: str | None) -> str:
    bits = [course or "the course"]
    if week is not None:
        bits.append(f"Week {week}")
    if topic:
        bits.append(topic)
    return " ".join(bits)


def _query(course: str | None, week: int | None, topic: str | None) -> str:
    return topic or (
        f"Week {week} key concepts and exam points" if week is not None
        else "key concepts and exam points"
    )


def _normalise_question(raw: dict) -> dict | None:
    qtype = str(raw.get("type", "")).lower()
    if qtype not in _VALID_TYPES:
        return None
    question = str(raw.get("question", "")).strip()
    answer = str(raw.get("answer", "")).strip()
    if not question or not answer:
        return None
    difficulty = str(raw.get("difficulty", "medium")).lower()
    if difficulty not in _VALID_DIFF:
        difficulty = "medium"
    options = raw.get("options") if qtype == "mcq" else None
    if qtype == "mcq":
        if not isinstance(options, list) or len(options) < 2:
            return None
        options = [str(o) for o in options]
        if answer not in options:
            return None
    return {
        "type": qtype,
        "question": question,
        "options": options,
        "answer": answer,
        "concept": str(raw.get("concept", "General")).strip() or "General",
        "difficulty": difficulty,
        "explanation": str(raw.get("explanation", "")).strip(),
        "sources": [str(s) for s in raw.get("sources", []) if isinstance(s, str)],
    }


def _persist(
    session: Session,
    course: str | None,
    week: int | None,
    topic: str | None,
    questions: list[dict],
) -> Quiz:
    quiz = Quiz(course=course, week=week, topic=topic)
    session.add(quiz)
    session.flush()
    for i, q in enumerate(questions):
        concept = get_or_create_concept(session, course, q["concept"])
        session.add(
            QuizQuestion(
                quiz_id=quiz.id,
                index=i,
                type=q["type"],
                question=q["question"],
                options=q["options"],
                answer_key=q["answer"],
                explanation=q["explanation"],
                difficulty=q["difficulty"],
                concept_id=concept.id,
                concept_name=q["concept"],
                sources=q["sources"],
            )
        )
    session.flush()
    return quiz


def generate_quiz(
    *,
    course: str | None = None,
    week: int | None = None,
    topic: str | None = None,
    num_questions: int = 5,
    settings: Settings | None = None,
    adapter: ChatAdapter | None = None,
) -> QuizResult:
    settings = settings or get_settings()
    adapter = adapter or get_chat_adapter(settings)

    flt = MetadataFilter(course=course, week=week)
    retrieval = search(
        _query(course, week, topic), settings=settings, flt=flt, final_limit=12
    )
    context = build_context(retrieval.hits)
    if context.is_empty:
        return QuizResult(
            None, course, week, topic,
            warnings=["No sources found for this scope; cannot generate a quiz."],
        )

    messages = [
        ChatMessage(role="system", content=QUIZ_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=build_quiz_prompt(
                _scope(course, week, topic), num_questions, context.text
            ),
        ),
    ]
    try:
        response = adapter.generate(messages, temperature=settings.generation.temperature)
        data = extract_json(response.content)
    except (ChatError, ValueError) as exc:
        logger.warning("Quiz generation failed: %s", exc)
        return QuizResult(None, course, week, topic, warnings=[str(exc)])

    raw_questions = data.get("questions", []) if isinstance(data, dict) else []
    questions = [q for q in (_normalise_question(r) for r in raw_questions) if q]
    if not questions:
        return QuizResult(
            None, course, week, topic,
            warnings=["Model returned no valid questions."],
        )

    with session_scope(settings) as session:
        quiz = _persist(session, course, week, topic, questions)
        quiz_id = quiz.id
        client_questions = [
            {
                "id": q.id,
                "index": q.index,
                "type": q.type,
                "question": q.question,
                "options": q.options,
                "difficulty": q.difficulty,
                "concept": q.concept_name,
            }
            for q in quiz.questions
        ]

    return QuizResult(quiz_id, course, week, topic, questions=client_questions)
