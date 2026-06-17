"""Fuse keyword + vector results with Reciprocal Rank Fusion + trust weighting."""

from __future__ import annotations

from dataclasses import replace

from app.retrieval.types import SearchHit

# Trust levels run 1 (most trusted) .. 8 (least). Map to a [0,1] bonus.
_MIN_TRUST, _MAX_TRUST = 1, 8


def _trust_bonus(trust_level: int, trust_weight: float) -> float:
    span = _MAX_TRUST - _MIN_TRUST
    norm = (_MAX_TRUST - trust_level) / span
    norm = max(0.0, min(1.0, norm))
    return trust_weight * norm


def reciprocal_rank_fusion(
    result_lists: list[list[SearchHit]], *, rrf_k: int = 60
) -> tuple[dict[int, float], dict[int, SearchHit]]:
    scores: dict[int, float] = {}
    hit_by_id: dict[int, SearchHit] = {}
    for hits in result_lists:
        for rank, h in enumerate(hits):
            scores[h.chunk_id] = scores.get(h.chunk_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            hit_by_id.setdefault(h.chunk_id, h)
    return scores, hit_by_id


def fuse(
    keyword_hits: list[SearchHit],
    vector_hits: list[SearchHit],
    *,
    rrf_k: int = 60,
    trust_weight: float = 0.15,
    final_limit: int = 8,
) -> list[SearchHit]:
    scores, hit_by_id = reciprocal_rank_fusion(
        [keyword_hits, vector_hits], rrf_k=rrf_k
    )
    fused: list[SearchHit] = []
    for cid, base in scores.items():
        h = hit_by_id[cid]
        final = base + _trust_bonus(h.trust_level, trust_weight)
        fused.append(replace(h, score=final, retrieval="hybrid"))
    # Stable tie-break: score desc, then more-trusted, then chunk id.
    fused.sort(key=lambda x: (-x.score, x.trust_level, x.chunk_id))
    return fused[:final_limit]
