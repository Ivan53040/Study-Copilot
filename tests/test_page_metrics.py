from __future__ import annotations

import pytest

from evals.page_metrics import score_pages


def test_page_metrics_use_all_relevant_pages_and_graded_gain():
    scores = score_pages(["b", "other", "a"], {"a": 2, "b": 1}, 3)
    assert scores["recall"] == 1
    assert scores["mrr"] == 1
    assert scores["map"] == pytest.approx(5 / 6)
    assert scores["ndcg"] == pytest.approx(2.5 / (3 + 1 / 1.584962500721156))


def test_page_metrics_penalize_missing_relevant_pages():
    scores = score_pages(["a"], {"a": 2, "b": 1}, 1)
    assert scores["recall"] == 0.5
    assert scores["map"] == 0.5
    assert scores["ndcg"] == 1
