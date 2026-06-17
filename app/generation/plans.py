"""Render weak-topic reports and daily study plans as Obsidian notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.learning.planner import build_daily_plan, weak_topics
from app.obsidian.templates import render_frontmatter
from app.obsidian.writer import safe_filename, write_note

_PLANS_DIR = "StudyCopilot/Daily Plans"
_REPORTS_DIR = "StudyCopilot/Reports"


@dataclass
class PlanResult:
    title: str
    target_path: str
    content: str
    data: dict
    written: bool = False

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "target_path": self.target_path,
            "content": self.content,
            "data": self.data,
            "written": self.written,
        }


def _status_emoji(status: str) -> str:
    return {"weak": "🔴", "developing": "🟠", "good": "🟡", "strong": "🟢"}.get(
        status, "⚪"
    )


def generate_daily_plan(
    *,
    course: str | None = None,
    available_minutes: int = 60,
    exam_date: str | None = None,
    settings: Settings | None = None,
    write: bool = False,
) -> PlanResult:
    settings = settings or get_settings()
    with session_scope(settings) as session:
        plan = build_daily_plan(
            session,
            course=course,
            available_minutes=available_minutes,
            exam_date=exam_date,
        )
    data = plan.as_dict()

    title = f"{course or 'Study'} Daily Plan {plan.date}"
    fm = render_frontmatter(
        {
            "title": title,
            "course": course,
            "type": "daily-plan",
            "source_type": "ai-generated",
            "generated_at": date.today().isoformat(),
            "available_minutes": available_minutes,
            **({"exam_date": exam_date} if exam_date else {}),
        }
    )

    lines = [fm, ""]
    if plan.days_until_exam is not None:
        lines.append(f"**Exam in {plan.days_until_exam} day(s)** ({exam_date})\n")
    lines.append(f"_Plan for {plan.date} — {available_minutes} min available._\n")
    if not plan.blocks:
        lines.append("No weak topics to review — take a quiz to surface gaps.")
    else:
        lines.append("| # | Concept | Time | Focus |")
        lines.append("|---|---------|------|-------|")
        for i, b in enumerate(plan.blocks, start=1):
            lines.append(
                f"| {i} | {_status_emoji(b['status'])} {b['concept']} "
                f"| {b['minutes']} min | {b['action']} |"
            )
    content = "\n".join(lines) + "\n"

    target_rel = f"{_PLANS_DIR}/{safe_filename(title)}.md"
    result = PlanResult(title, target_rel, content, data)
    if write:
        wr = write_note(target_rel, content, settings)
        result.written = True
        result.target_path = wr.path
    return result


def generate_weak_topic_report(
    *,
    course: str | None = None,
    settings: Settings | None = None,
    write: bool = False,
) -> PlanResult:
    settings = settings or get_settings()
    with session_scope(settings) as session:
        topics = [t.as_dict() for t in weak_topics(session, course)]

    title = f"{course or 'Study'} Weak Topics {date.today().isoformat()}"
    fm = render_frontmatter(
        {
            "title": title,
            "course": course,
            "type": "weak-topic-report",
            "source_type": "ai-generated",
            "generated_at": date.today().isoformat(),
        }
    )
    lines = [fm, "", f"_{len(topics)} concept(s) need attention._\n"]
    if topics:
        lines.append("| Concept | Confidence | Status | Exam freq | Due |")
        lines.append("|---------|-----------|--------|-----------|-----|")
        for t in topics:
            lines.append(
                f"| {t['name']} | {round(t['confidence']*100)}% "
                f"| {_status_emoji(t['status'])} {t['status']} "
                f"| {t['exam_frequency']} | {'⏰' if t['due'] else ''} |"
            )
    else:
        lines.append("No weak topics — nice work.")
    content = "\n".join(lines) + "\n"

    target_rel = f"{_REPORTS_DIR}/{safe_filename(title)}.md"
    result = PlanResult(title, target_rel, content, {"topics": topics})
    if write:
        wr = write_note(target_rel, content, settings)
        result.written = True
        result.target_path = wr.path
    return result
