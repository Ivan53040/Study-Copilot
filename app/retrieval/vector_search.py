"""Vector search via brute-force cosine similarity over stored embeddings.

For an MVP-sized corpus (a few thousand chunks) a numpy matmul is instant and
far simpler than a dedicated vector DB. The ``VectorStore`` boundary here can be
swapped for Chroma/Qdrant later without touching callers.
"""

from __future__ import annotations

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.retrieval.filters import metadata_clause
from app.retrieval.types import MetadataFilter, SearchHit


def _normalize_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def vector_search(
    session: Session,
    query_vector: list[float],
    *,
    model: str,
    flt: MetadataFilter | None = None,
    limit: int = 20,
) -> list[SearchHit]:
    flt = flt or MetadataFilter()
    params: dict = {"model": model}
    where_extra = metadata_clause(flt, params)

    sql = text(
        f"""
        SELECT c.id, c.document_id, c.content, c.heading, c.page_number,
               c.course, c.week, c.source_type, c.trust_level,
               d.title, d.path, e.vector
        FROM chunk_embeddings e
        JOIN chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.model = :model{where_extra}
        """
    )
    rows = session.execute(sql, params).all()
    if not rows:
        return []

    mat = np.stack([np.frombuffer(r.vector, dtype=np.float32) for r in rows])
    q = np.asarray(query_vector, dtype=np.float32)
    if mat.shape[1] != q.shape[0]:
        # Dimension mismatch (model changed) — nothing comparable.
        return []

    sims = _normalize_rows(mat) @ (q / (np.linalg.norm(q) or 1.0))
    top_idx = np.argsort(-sims)[:limit]

    hits: list[SearchHit] = []
    for i in top_idx:
        r = rows[int(i)]
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
                score=float(sims[int(i)]),
                retrieval="vector",
            )
        )
    return hits
