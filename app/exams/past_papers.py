"""Extract questions from past papers, link concepts, estimate exam frequency.

Extraction is heuristic (works offline): split document text on question markers
and pull marks. Concepts are linked by matching against known concept names; if
none match, the question is filed under "General". Once linked, each concept's
``exam_frequency`` is set to how many past-paper questions reference it — which
feeds straight into study-plan prioritisation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.database.models import Chunk, Concept, Document, PastPaperQuestion
from app.ingestion.hashing import sha256_text
from app.learning.concepts import get_or_create_concept
from app.logging_config import get_logger

logger = get_logger("exams.past_papers")

# Question starts: "Question 3", "3.", "3)" possibly preceded by "QUESTION".
_Q_RE = re.compile(r"(?im)^\s*(?:question\s+)?(\d{1,2})[\.\):]\s+")
_MARKS_RE = re.compile(r"\((\d+)\s*marks?\)", re.IGNORECASE)
_MIN_Q_LEN = 25


@dataclass
class AnalyzeReport:
    course: str | None
    documents: int = 0
    questions: int = 0
    concepts_updated: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "course": self.course,
            "documents": self.documents,
            "questions": self.questions,
            "concepts_updated": self.concepts_updated,
            "warnings": self.warnings,
        }


def split_questions(text: str) -> list[dict]:
    """Split past-paper text into {number, text, marks} question dicts."""
    matches = list(_Q_RE.finditer(text))
    out: list[dict] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < _MIN_Q_LEN:
            continue
        marks_m = _MARKS_RE.search(body)
        out.append(
            {
                "number": m.group(1),
                "text": body,
                "marks": int(marks_m.group(1)) if marks_m else None,
            }
        )
    return out


def link_concept(text: str, concept_names: list[str]) -> str:
    """Pick the first known concept whose name appears in the question."""
    low = text.lower()
    best = None
    for name in concept_names:
        if name and name.lower() in low:
            # Prefer the longest (most specific) match.
            if best is None or len(name) > len(best):
                best = name
    return best or "General"


def _past_paper_documents(session: Session, course: str | None) -> list[Document]:
    q = select(Document).where(
        (Document.source_type == "past-paper")
        | (Document.document_type == "past-paper")
    )
    if course:
        q = q.where(Document.course == course.replace(" ", "").upper())
    return list(session.scalars(q).all())


def _doc_text(session: Session, document_id: int) -> str:
    chunks = session.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
    ).all()
    return "\n".join(c.content for c in chunks)


def analyze_past_papers(
    course: str | None = None, settings: Settings | None = None
) -> AnalyzeReport:
    settings = settings or get_settings()
    report = AnalyzeReport(course=course)

    with session_scope(settings) as session:
        docs = _past_paper_documents(session, course)
        report.documents = len(docs)
        if not docs:
            report.warnings.append("No past-paper documents found for this course.")
            return report

        concept_names = [
            n for (n,) in session.execute(select(Concept.name)).all()
        ]

        # Re-analysis replaces prior extraction for these documents.
        doc_ids = [d.id for d in docs]
        for ppq in session.scalars(
            select(PastPaperQuestion).where(
                PastPaperQuestion.document_id.in_(doc_ids)
            )
        ).all():
            session.delete(ppq)
        session.flush()

        freq: dict[str, int] = {}
        for doc in docs:
            text = _doc_text(session, doc.id)
            for q in split_questions(text):
                concept_name = link_concept(q["text"], concept_names)
                concept = get_or_create_concept(session, doc.course, concept_name)
                session.add(
                    PastPaperQuestion(
                        course=doc.course,
                        document_id=doc.id,
                        number=q["number"],
                        text=q["text"][:4000],
                        marks=q["marks"],
                        concept_id=concept.id,
                        concept_name=concept_name,
                        content_hash=sha256_text(q["text"]),
                    )
                )
                report.questions += 1
                freq[concept_name] = freq.get(concept_name, 0) + 1

        # Update exam frequency on every concept (0 if not seen this run).
        all_concepts = session.scalars(select(Concept)).all()
        for c in all_concepts:
            new_freq = freq.get(c.name, 0)
            if c.exam_frequency != new_freq:
                c.exam_frequency = new_freq
                report.concepts_updated += 1

    logger.info("Past-paper analysis: %s", report.as_dict())
    return report


def list_past_paper_questions(
    course: str | None = None, settings: Settings | None = None
) -> list[dict]:
    settings = settings or get_settings()
    with session_scope(settings) as session:
        q = select(PastPaperQuestion)
        if course:
            q = q.where(
                PastPaperQuestion.course == course.replace(" ", "").upper()
            )
        rows = session.scalars(q.order_by(PastPaperQuestion.concept_name)).all()
        return [
            {
                "id": r.id,
                "number": r.number,
                "marks": r.marks,
                "concept": r.concept_name,
                "text": r.text[:300],
            }
            for r in rows
        ]
