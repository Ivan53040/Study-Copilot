"""Daily study plan + weak-topic report endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config.settings import Settings, get_settings
from app.generation.plans import generate_daily_plan, generate_weak_topic_report

router = APIRouter(tags=["plans"])


class DailyPlanRequest(BaseModel):
    course: str | None = None
    available_minutes: int = 60
    exam_date: str | None = None  # ISO date, e.g. "2026-07-01"
    write: bool = False


class WeakTopicRequest(BaseModel):
    course: str | None = None
    write: bool = False


@router.post("/plans/daily")
def post_daily_plan(
    req: DailyPlanRequest, settings: Settings = Depends(get_settings)
) -> dict:
    result = generate_daily_plan(
        course=req.course,
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
    result = generate_weak_topic_report(
        course=req.course, settings=settings, write=req.write
    )
    return result.as_dict()
