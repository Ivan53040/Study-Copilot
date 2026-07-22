"""Daily study plan + weak-topic report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.generation.plans import generate_daily_plan, generate_weak_topic_report
from app.study_sets.service import resolve_scope

router = APIRouter(tags=["plans"])


class DailyPlanRequest(BaseModel):
    course: str | None = None
    study_set_id: int | None = None
    available_minutes: int = 60
    exam_date: str | None = None  # ISO date, e.g. "2026-07-01"
    write: bool = False


class WeakTopicRequest(BaseModel):
    course: str | None = None
    study_set_id: int | None = None
    write: bool = False


@router.post("/plans/daily")
def post_daily_plan(
    req: DailyPlanRequest, settings: Settings = Depends(get_settings)
) -> dict:
    resolved = resolve_scope(
        settings=settings, study_set_id=req.study_set_id, course=req.course
    )
    result = generate_daily_plan(
        course=resolved.course,
        available_minutes=req.available_minutes,
        exam_date=req.exam_date,
        settings=settings,
        write=req.write,
    )
    return result.as_dict()


@router.post("/reports/weak-topics")
def post_weak_topics(
    req: WeakTopicRequest, settings: Settings = Depends(get_settings)
) -> dict:
    resolved = resolve_scope(
        settings=settings, study_set_id=req.study_set_id, course=req.course
    )
    result = generate_weak_topic_report(
        course=resolved.course, settings=settings, write=req.write
    )
    return result.as_dict()
