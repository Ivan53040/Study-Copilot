"""The Today page: upcoming deadlines, reviews due, weak topics, a short plan."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Deadline, LearningEvent, Quiz
from app.learning.planner import build_daily_plan, rank_topics

router = APIRouter(tags=["today"])

_KINDS = {"exam", "assignment", "other"}


class DeadlineIn(BaseModel):
    title: str
    date: date
    course: str | None = None
    kind: str = "exam"

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Give the deadline a name.")
        return value[:200]

    @field_validator("kind")
    @classmethod
    def _kind(cls, value: str) -> str:
        value = value.lower().strip()
        return value if value in _KINDS else "other"

    @field_validator("course")
    @classmethod
    def _course(cls, value: str | None) -> str | None:
        value = (value or "").replace(" ", "").upper()
        return value or None


def _deadline_dict(row: Deadline, today: date) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "course": row.course,
        "kind": row.kind,
        "date": row.due_date.isoformat(),
        "days_until": (row.due_date - today).days,
    }


def _norm_course(course: str | None) -> str | None:
    return course.replace(" ", "").upper() if course else None


@router.get("/deadlines")
def list_deadlines(
    include_past: bool = False, settings: Settings = Depends(get_settings)
) -> dict:
    today = date.today()
    with session_scope(settings) as session:
        query = select(Deadline).order_by(Deadline.due_date, Deadline.id)
        if not include_past:
            query = query.where(Deadline.due_date >= today)
        rows = session.scalars(query).all()
        return {"deadlines": [_deadline_dict(row, today) for row in rows]}


@router.post("/deadlines")
def create_deadline(body: DeadlineIn, settings: Settings = Depends(get_settings)) -> dict:
    with session_scope(settings) as session:
        row = Deadline(title=body.title, course=body.course, kind=body.kind, due_date=body.date)
        session.add(row)
        session.flush()
        return _deadline_dict(row, date.today())


@router.delete("/deadlines/{deadline_id}")
def delete_deadline(deadline_id: int, settings: Settings = Depends(get_settings)) -> dict:
    with session_scope(settings) as session:
        row = session.get(Deadline, deadline_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Deadline not found")
        session.delete(row)
        return {"deleted": deadline_id}


@router.get("/today")
def get_today(
    course: str | None = None,
    minutes: int = 60,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Everything the Today page shows, in one call."""
    today = date.today()
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    course = _norm_course(course)
    minutes = max(15, min(minutes, 480))

    with session_scope(settings) as session:
        deadline_query = (
            select(Deadline)
            .where(Deadline.due_date >= today)
            .order_by(Deadline.due_date, Deadline.id)
        )
        if course:
            deadline_query = deadline_query.where(
                (Deadline.course == course) | (Deadline.course.is_(None))
            )
        deadlines = [_deadline_dict(row, today) for row in session.scalars(deadline_query).all()]

        ranked = rank_topics(session, course, now)
        due = [topic.as_dict() for topic in ranked if topic.due]
        weak = [
            topic.as_dict()
            for topic in ranked
            if not topic.due and (topic.status in {"weak", "developing"} or topic.confidence < 0.70)
        ]
        tracked = len(ranked)
        average = round(sum(t.confidence for t in ranked) / tracked, 3) if tracked else None

        next_exam = next((d for d in deadlines if d["kind"] == "exam"), None)
        plan = build_daily_plan(
            session,
            course=course or (next_exam or {}).get("course"),
            available_minutes=minutes,
            exam_date=next_exam["date"] if next_exam else None,
            now=now,
        ).as_dict()

        answers_week = session.scalar(
            select(func.count(LearningEvent.id)).where(
                LearningEvent.timestamp >= week_ago.replace(tzinfo=None),
                LearningEvent.event_type.in_(["correct", "incorrect", "partial"]),
            )
        ) or 0
        quizzes_week = session.scalar(
            select(func.count(Quiz.id)).where(
                Quiz.submitted_at.is_not(None),
                Quiz.submitted_at >= week_ago.replace(tzinfo=None),
            )
        ) or 0

    return {
        "date": today.isoformat(),
        "course": course,
        "deadlines": deadlines,
        "due": due[:12],
        "due_count": len(due),
        "weak": weak[:8],
        "plan": plan,
        "stats": {
            "concepts": tracked,
            "average_confidence": average,
            "answers_this_week": int(answers_week),
            "quizzes_this_week": int(quizzes_week),
        },
    }
