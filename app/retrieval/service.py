"""High-level search: keyword + vector -> hybrid, with graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.database.db import session_scope
from app.logging_config import get_logger
from app.models.embeddings import get_embedding_provider
from app.retrieval.hybrid_search import fuse
from app.retrieval.keyword_search import keyword_search
from app.retrieval.types import MetadataFilter, SearchHit
from app.retrieval.vector_search import vector_search
from app.wiki import store

logger = get_logger("retrieval.service")

_WIKI_TRUST_LEVEL = 7


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
        fused = _include_wiki_hits(
            session=session,
            query=query,
            settings=settings,
            flt=flt or MetadataFilter(),
            hits=fused,
            final_limit=final_limit,
        )

    return SearchResponse(
        query=query, hits=fused, used_vector=used_vector, note=note
    )


def _include_wiki_hits(
    *,
    session,
    query: str,
    settings: Settings,
    flt: MetadataFilter,
    hits: list[SearchHit],
    final_limit: int,
) -> list[SearchHit]:
    wiki_filter = _wiki_filter(settings, flt)
    if wiki_filter is None or final_limit <= 1:
        return hits

    desired = min(2, max(1, final_limit // 4))
    existing = {_normal_path(hit.path) for hit in hits}
    existing_wiki = sum(
        1 for hit in hits if _is_wiki_path(hit.path, settings)
    )
    if existing_wiki >= desired:
        return hits[:final_limit]

    wiki_hits = keyword_search(
        session,
        query,
        flt=wiki_filter,
        limit=max(4, desired * 4),
    )
    additions = [
        hit
        for hit in wiki_hits
        if _normal_path(hit.path) not in existing
    ][: desired - existing_wiki]
    if not additions:
        return hits[:final_limit]

    keep_count = max(0, final_limit - len(additions))
    return [*hits[:keep_count], *additions]


def _wiki_filter(settings: Settings, flt: MetadataFilter) -> MetadataFilter | None:
    if flt.path_prefix or flt.document_ids or flt.source_type:
        return None
    if flt.max_trust_level is not None and flt.max_trust_level < _WIKI_TRUST_LEVEL:
        return None

    root = Path(settings.vault.root).expanduser().resolve()
    if flt.course:
        prefix = root / store.wiki_course_dir(flt.course, settings)
    else:
        prefix = root / settings.wiki.root
    if not prefix.exists():
        return None
    return MetadataFilter(
        course=flt.course,
        path_prefix=str(prefix),
        max_trust_level=flt.max_trust_level,
    )


def _is_wiki_path(path: str, settings: Settings) -> bool:
    root = Path(settings.vault.root).expanduser().resolve()
    try:
        Path(path).resolve().relative_to(root / settings.wiki.root)
        return True
    except (ValueError, OSError):
        return False


def _normal_path(path: str) -> str:
    return str(Path(path).expanduser().resolve()).lower()
