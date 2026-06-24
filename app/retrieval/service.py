"""High-level search: keyword + vector -> hybrid, with graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.logging_config import get_logger
from app.models.embeddings import get_embedding_provider
from app.retrieval.hybrid_search import fuse
from app.retrieval.keyword_search import keyword_search
from app.retrieval.types import MetadataFilter, SearchHit
from app.retrieval.vector_search import vector_search

logger = get_logger("retrieval.service")


@dataclass
class SearchResponse:
    query: str
    hits: list[SearchHit]
    used_vector: bool
    note: str | None = None


def search(
    query: str,
    *,
    settings: Settings | None = None,
    flt: MetadataFilter | None = None,
    final_limit: int | None = None,
) -> SearchResponse:
    settings = settings or get_settings()
    rc = settings.retrieval
    final_limit = final_limit or rc.final_context_limit

    with session_scope(settings) as session:
        kw_hits = keyword_search(
            session, query, flt=flt, limit=rc.keyword_limit
        )

        vec_hits: list[SearchHit] = []
        used_vector = False
        note = None
        provider = get_embedding_provider(settings)
        try:
            qv = provider.embed([query])[0]
            vec_hits = vector_search(
                session, qv, model=provider.model_name, flt=flt, limit=rc.vector_limit
            )
            used_vector = True
            if not vec_hits:
                note = (
                    "No vector results (run `python -m scripts.embed` to index "
                    "embeddings, or check the embedding model)."
                )
        except Exception as exc:
            # Embedding endpoint down/misconfigured -> keyword-only, still useful.
            logger.warning("Vector search unavailable, using keyword-only: %s", exc)
            note = f"Embeddings unavailable ({exc}); keyword-only results."

        fused = fuse(
            kw_hits,
            vec_hits,
            rrf_k=rc.rrf_k,
            trust_weight=rc.trust_weight,
            final_limit=final_limit,
        )

    return SearchResponse(
        query=query, hits=fused, used_vector=used_vector, note=note
    )
