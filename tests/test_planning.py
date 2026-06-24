"""Phase 6 tests: topic ranking, daily plan, reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.db import session_scope
from app.database.models import Concept, ConceptProgress
from app.generation.plans import generate_daily_plan, generate_weak_topic_report
from app.learning.planner import build_daily_plan, rank_topics, weak_topics


def _seed(session, name, confidence, *, exam_freq=0, status="weak", due=False):
    c = Concept(course="REIT6811", name=name, exam_frequency=exam_freq)
    session.add(c)
    session.flush()
    nr = (
        datetime.now(timezone.utc) - timedelta(days=1)
        if due
        else datetime.now(timezone.utc) + timedelta(days=5)
    )
    session.add(
        ConceptProgress(
            concept_id=c.id, confidence=confidence, status=status, next_review=nr
        )
    )
    return c


@pytest.fixture
def seeded(settings, db):
    with session_scope(settings) as s:
        _seed(s, "Reliability", 0.2, status="weak", exam_freq=3)
        _seed(s, "Validity", 0.5, status="developing", exam_freq=1)
        _seed(s, "Sampling", 0.95, status="strong", exam_freq=0)
    return settings


def test_rank_orders_low_confidence_first(seeded):
    with session_scope(seeded) as s:
        ranked = rank_topics(s, "REIT6811")
    assert ranked[0].name == "Reliability"  # lowest confidence + high freq
    # Strong concept ranks last.
    assert ranked[-1].name == "Sampling"


def test_weak_topics_excludes_strong(seeded):
    with session_scope(seeded) as s:
        weak = [t.name for t in weak_topics(s, "REIT6811")]
    assert "Reliability" in weak and "Validity" in weak
    assert "Sampling" not in weak


def test_daily_plan_respects_time_budget(seeded):
    with session_scope(seeded) as s:
        plan = build_daily_plan(s, course="REIT6811", available_minutes=60)
    # 60 // 25 = 2 blocks.
    assert len(plan.blocks) == 2
    assert plan.blocks[0]["concept"] == "Reliability"
    assert plan.blocks[0]["action"]


def test_daily_plan_exam_countdown(seeded):
    future = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    with session_scope(seeded) as s:
        plan = build_daily_plan(
            s, course="REIT6811", available_minutes=30, exam_date=future
        )
    assert plan.days_until_exam == 10


def test_generate_daily_plan_writes_to_studycopilot(seeded):
    res = generate_daily_plan(
        course="REIT6811", available_minutes=50, settings=seeded, write=True
    )
    assert res.written
    from pathlib import Path

    p = Path(res.target_path)
    assert p.exists()
    assert seeded.output_root.resolve() in p.resolve().parents
    assert "Daily Plan" in p.read_text(encoding="utf-8")


def test_weak_topic_report_preview(seeded):
    res = generate_weak_topic_report(course="REIT6811", settings=seeded, write=False)
    assert "Reliability" in res.content
    assert res.written is False
