"""Shared retrieval types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SearchHit:
    chunk_id: int
    document_id: int
    content: str
    heading: str | None
    page_number: int | None
    course: str | None
    week: int | None
    source_type: str | None
    trust_level: int
    title: str
    path: str
    score: float
    retrieval: str  # "keyword" | "vector" | "hybrid"

    def as_dict(self, *, include_content: bool = True) -> dict:
        d = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "heading": self.heading,
            "page_number": self.page_number,
            "course": self.course,
            "week": self.week,
            "source_type": self.source_type,
            "trust_level": self.trust_level,
            "title": self.title,
            "path": self.path,
            "score": round(self.score, 5),
            "retrieval": self.retrieval,
        }
        if include_content:
            d["content"] = self.content
        return d


@dataclass
class MetadataFilter:
    course: str | None = None
    week: int | None = None
    source_type: str | None = None
    max_trust_level: int | None = None  # keep only sources at least this trusted
