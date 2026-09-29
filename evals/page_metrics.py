"""IR metrics for human-labelled, page-level relevance judgments."""

from __future__ import annotations

import math


def score_pages(ranked: list[str], relevance: dict[str, int], k: int) -> dict[str, float]:
    """Grades: 0 irrelevant, 1 relevant, 2 highly relevant."""
    if k < 1:
        raise ValueError("k must be positive")
    ranked = ranked[:k]
    relevant_total = sum(grade > 0 for grade in relevance.values())
    found = 0
    precision_sum = 0.0
    reciprocal_rank = 0.0
    dcg = 0.0
    for rank, page in enumerate(ranked, 1):
        grade = relevance.get(page, 0)
        if grade > 0:
            found += 1
            precision_sum += found / rank
            if not reciprocal_rank:
                reciprocal_rank = 1 / rank
        dcg += (2**grade - 1) / math.log2(rank + 1)
    ideal_grades = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, 1))
    return {
        "recall": found / relevant_total if relevant_total else 0.0,
        "mrr": reciprocal_rank,
        "map": precision_sum / relevant_total if relevant_total else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
    }
