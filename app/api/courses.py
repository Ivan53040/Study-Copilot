"""Course and document listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Document

router = APIRouter(tags=["courses"])


@router.get("/courses")
def list_courses(settings: Settings = Depends(get_settings)) -> dict:
    with session_scope(settings) as session:
        rows = session.execute(
            select(
                Document.course,
                func.count(func.distinct(Document.id)),
                func.count(Chunk.id),
            )
            .outerjoin(Chunk, Chunk.document_id == Document.id)
            .group_by(Document.course)
        ).all()
    courses = [
        {"course": course or "(unclassified)", "documents": docs, "chunks": chunks}
        for course, docs, chunks in rows
    ]
    return {"courses": courses}


@router.get("/courses/{course}/documents")
def list_documents(
    course: str, settings: Settings = Depends(get_settings)
) -> dict:
    normalised = course.replace(" ", "").upper()
    with session_scope(settings) as session:
        docs = session.scalars(
            select(Document)
            .where(func.upper(Document.course) == normalised)
            .order_by(Document.week, Document.title)
        ).all()
        result = [
            {
                "id": d.id,
                "title": d.title,
                "week": d.week,
                "document_type": d.document_type,
                "source_type": d.source_type,
                "trust_level": d.trust_level,
                "chunks": len(d.chunks),
                "path": d.path,
            }
            for d in docs
        ]
    return {"course": normalised, "count": len(result), "documents": result}
