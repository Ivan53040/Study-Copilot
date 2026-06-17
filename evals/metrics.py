"""Retrieval metrics: keyword-presence recall@k and MRR.

We use a keyword-presence proxy for ground truth: a query is "answerable" at k
if the expected keyword(s) appear in the content of the top-k retrieved chunks.
It is honest (easy to label correctly) and runs offline. ``mode``:
  * "any" — at least one expected keyword present (lenient)
  * "all" — every expected keyword present (strict)
"""

from __future__ import annotations

from app.retrieval.types import SearchHit


def _present(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def keyword_hit(hits: list[SearchHit], keywords: list[str], mode: str = "any") -> bool:
    blob = "\n".join(h.content or "" for h in hits)
    checks = [_present(blob, kw) for kw in keywords]
    return any(checks) if mode == "any" else all(checks)


def first_hit_rank(hits: list[SearchHit], keywords: list[str]) -> int | None:
    """1-based rank of the first chunk containing any expected keyword."""
    for i, h in enumerate(hits, start=1):
        if any(_present(h.content or "", kw) for kw in keywords):
            return i
    return None


def reciprocal_rank(hits: list[SearchHit], keywords: list[str]) -> float:
    rank = first_hit_rank(hits, keywords)
    return 1.0 / rank if rank else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
