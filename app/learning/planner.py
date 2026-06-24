"""Study planning: rank weak topics and build a daily plan.

Priorities are computed deterministically and transparently from recorded
evidence — low confidence, high exam frequency, and being due for review all
push a concept up the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Concept, ConceptProgress

W_CONFIDENCE = 0.5
W_FREQUENCY = 0.3
W_DUE = 0.2

BLOCK_MINUTES = 25  # one focused study block


@dataclass
class TopicPriority:
    concept_id: int
    name: str
    course: str | None
    confidence: float
    status: str
    exam_frequency: int
    due: bool
    priority: float

    def as_dict(self) -> dict:
        return {
            "concept_id": self.concept_id,
            "name": self.name,
            "course": self.course,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "exam_frequency": self.exam_frequency,
            "due": self.due,
            "priority": round(self.priority, 3),
        }


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def rank_topics(
    session: Session, course: str | None = None, now: datetime | None = None
) -> list[TopicPriority]:
    now = _now(now)
    q = select(Concept)
    if course:
        q = q.where(Concept.course == course.replace(" ", "").upper())
    concepts = session.scalars(q).all()
    max_freq = max((c.exam_frequency for c in concepts), default=0)

    ranked: list[TopicPriority] = []
    for c in concepts:
        p: ConceptProgress | None = c.progress
        confidence = p.confidence if p else 0.0
        status = p.status if p else "weak"
        due = bool(p and p.next_review and _aware(p.next_review) <= now)
        freq_norm = (c.exam_frequency / max_freq) if max_freq > 0 else 0.0
        priority = (
            W_CONFIDENCE * (1.0 - confidence)
            + W_FREQUENCY * freq_norm
            + W_DUE * (1.0 if due else 0.0)
        )
        ranked.append(
            TopicPriority(
                concept_id=c.id,
                name=c.name,
                course=c.course,
                confidence=confidence,
                status=status,
                exam_frequency=c.exam_frequency,
                due=due,
                priority=priority,
            )
        )
    ranked.sort(key=lambda t: (-t.priority, t.confidence, t.name))
    return ranked


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def weak_topics(
    session: Session, course: str | None = None, now: datetime | None = None
) -> list[TopicPriority]:
    """Concepts that need work: weak/developing, low confidence, or due."""
    return [
        t
        for t in rank_topics(session, course, now)
        if t.status in {"weak", "developing"} or t.confidence < 0.70 or t.due
    ]


def _action_for(t: TopicPriority) -> str:
    if t.confidence < 0.40:
        return "Read the source notes, then generate a revision note"
    if t.confidence < 0.70:
        return "Take a short practice quiz and review mistakes"
    if t.due:
        return "Quick review (spaced repetition due)"
    return "Light review / active recall"


@dataclass
class StudyPlan:
    course: str | None
    date: str
    available_minutes: int
    exam_date: str | None
    days_until_exam: int | None
    blocks: list[dict]

    def as_dict(self) -> dict:
        return {
            "course": self.course,
            "date": self.date,
            "available_minutes": self.available_minutes,
            "exam_date": self.exam_date,
            "days_until_exam": self.days_until_exam,
            "blocks": self.blocks,
        }


def build_daily_plan(
    session: Session,
    *,
    course: str | None = None,
    available_minutes: int = 60,
    exam_date: str | None = None,
    now: datetime | None = None,
) -> StudyPlan:
    now = _now(now)
    topics = weak_topics(session, course, now)

    n_blocks = max(1, available_minutes // BLOCK_MINUTES)
    chosen = topics[:n_blocks]

    blocks: list[dict] = []
    remaining = available_minutes
    for i, t in enumerate(chosen):
        minutes = BLOCK_MINUTES if i < len(chosen) - 1 else remaining
        remaining -= BLOCK_MINUTES
        blocks.append(
            {
                "concept": t.name,
                "concept_id": t.concept_id,
                "minutes": max(BLOCK_MINUTES, minutes) if len(chosen) == 1 else minutes,
                "action": _action_for(t),
                "confidence": round(t.confidence, 3),
                "status": t.status,
                "exam_frequency": t.exam_frequency,
            }
        )

    days_until = None
    if exam_date:
        try:
            ed = datetime.fromisoformat(exam_date).replace(tzinfo=timezone.utc)
            days_until = (ed.date() - now.date()).days
        except ValueError:
            days_until = None

    return StudyPlan(
        course=course,
        date=now.date().isoformat(),
        available_minutes=available_minutes,
        exam_date=exam_date,
        days_until_exam=days_until,
        blocks=blocks,
    )
