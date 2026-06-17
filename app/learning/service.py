"""Record learning events and update concept progress/confidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Concept, ConceptProgress, LearningEvent
from app.learning.confidence import EventLike, compute_confidence, status_band
from app.learning.spaced_repetition import next_review_date


@dataclass
class Outcome:
    """One graded answer to fold into learning history."""

    concept_id: int | None
    course: str | None
    event_type: str  # correct | incorrect | partial
    score: float
    max_score: float
    difficulty: str | None = None
    source_reference: str | None = None
    quiz_question_id: int | None = None


def _record_event(session: Session, o: Outcome, now: datetime) -> None:
    session.add(
        LearningEvent(
            course=o.course,
            concept_id=o.concept_id,
            event_type=o.event_type,
            score=o.score,
            max_score=o.max_score,
            difficulty=o.difficulty,
            source_reference=o.source_reference,
            quiz_question_id=o.quiz_question_id,
            timestamp=now,
        )
    )


def _update_progress(
    session: Session, concept_id: int, latest_outcome: str, now: datetime
) -> ConceptProgress:
    events = session.scalars(
        select(LearningEvent).where(LearningEvent.concept_id == concept_id)
    ).all()
    event_likes = [
        EventLike(e.score, e.max_score, e.difficulty, e.timestamp) for e in events
    ]
    confidence, _ = compute_confidence(event_likes, now)

    prog = session.get(ConceptProgress, concept_id)
    if prog is None:
        prog = ConceptProgress(concept_id=concept_id)
        session.add(prog)

    prog.confidence = confidence
    prog.status = status_band(confidence)
    prog.correct_count = sum(1 for e in events if e.event_type == "correct")
    prog.incorrect_count = sum(1 for e in events if e.event_type == "incorrect")
    prog.partial_count = sum(1 for e in events if e.event_type == "partial")
    prog.last_reviewed = now
    prog.next_review = next_review_date(latest_outcome, confidence, now)
    return prog


def record_outcomes(session: Session, outcomes: list[Outcome]) -> dict[int, dict]:
    """Record events and refresh progress for each affected concept.

    Returns ``{concept_id: {confidence, status, next_review}}``.
    """
    now = datetime.now(timezone.utc)
    latest_by_concept: dict[int, str] = {}
    for o in outcomes:
        _record_event(session, o, now)
        if o.concept_id is not None:
            latest_by_concept[o.concept_id] = o.event_type
    session.flush()

    updates: dict[int, dict] = {}
    for concept_id, latest in latest_by_concept.items():
        prog = _update_progress(session, concept_id, latest, now)
        updates[concept_id] = {
            "confidence": round(prog.confidence, 3),
            "status": prog.status,
            "next_review": prog.next_review.isoformat() if prog.next_review else None,
        }
    return updates


def get_progress(session: Session, course: str | None = None) -> list[dict]:
    q = select(Concept)
    if course:
        q = q.where(Concept.course == course.replace(" ", "").upper())
    concepts = session.scalars(q).all()
    rows: list[dict] = []
    for c in concepts:
        p = c.progress
        rows.append(
            {
                "concept_id": c.id,
                "name": c.name,
                "course": c.course,
                "confidence": round(p.confidence, 3) if p else 0.0,
                "status": p.status if p else "weak",
                "correct": p.correct_count if p else 0,
                "incorrect": p.incorrect_count if p else 0,
                "partial": p.partial_count if p else 0,
                "last_reviewed": p.last_reviewed.isoformat()
                if p and p.last_reviewed
                else None,
                "next_review": p.next_review.isoformat()
                if p and p.next_review
                else None,
            }
        )
    rows.sort(key=lambda r: (r["confidence"], r["name"]))
    return rows
