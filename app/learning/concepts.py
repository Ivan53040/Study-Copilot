"""Concept lookup/creation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Concept


def get_or_create_concept(
    session: Session, course: str | None, name: str
) -> Concept:
    name = name.strip()
    concept = session.scalar(
        select(Concept).where(Concept.course == course, Concept.name == name)
    )
    if concept is None:
        concept = Concept(course=course, name=name)
        session.add(concept)
        session.flush()
    return concept
