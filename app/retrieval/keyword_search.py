"""Keyword search over chunks via SQLite FTS5 (BM25 ranking)."""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.retrieval.filters import metadata_clause
from app.retrieval.types import MetadataFilter, SearchHit

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def build_match_query(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Each word becomes a quoted term (so punctuation can't break the query),
    OR-joined for recall. Returns "" when there's nothing searchable.
    """
    tokens = _TOKEN_RE.findall(query.lower())
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


def keyword_search(
    session: Session,
    query: str,
    *,
    flt: MetadataFilter | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    flt = flt or MetadataFilter()
    match = build_match_query(query)
    if not match:
        return []

    params: dict = {"match": match, "limit": limit}
    where_extra = metadata_clause(flt, params)

    sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.heading, c.page_number,
               c.course, c.week, c.source_type, c.trust_level,
               d.title, d.path,
               bm25(chunks_fts) AS bm25
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        JOIN documents d ON d.id = c.document_id
        WHERE chunks_fts MATCH :match{where_extra}
        ORDER BY bm25
        LIMIT :limit
        """
    )
    rows = session.execute(sql, params).all()

    hits: list[SearchHit] = []
    for r in rows:
        # bm25 is lower-is-better; flip sign so higher score = more relevant.
        hits.append(
            SearchHit(
                chunk_id=r.id,
                document_id=r.document_id,
                content=r.content,
                heading=r.heading,
                page_number=r.page_number,
                course=r.course,
                week=r.week,
                source_type=r.source_type,
                trust_level=r.trust_level,
                title=r.title,
                path=r.path,
                score=-float(r.bm25),
                retrieval="keyword",
            )
        )
    return hits
