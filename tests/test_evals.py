"""Phase 8 tests: eval metrics + harness suites."""

from __future__ import annotations

import pytest

from app.ingestion.service import ingest
from app.retrieval.indexing import index_embeddings
from app.retrieval.types import SearchHit
from evals import metrics
from evals.runner import run_marking_consistency, run_retrieval, run_safety


def _hit(content: str) -> SearchHit:
    return SearchHit(
        chunk_id=1, document_id=1, content=content, heading=None, page_number=None,
        course="REIT6811", week=None, source_type="user-note", trust_level=5,
        title="Doc", path="/v/Doc.md", score=1.0, retrieval="hybrid",
    )


# ---- metrics ----

def test_keyword_hit_any_and_all():
    hits = [_hit("reliability is consistency"), _hit("sampling methods")]
    assert metrics.keyword_hit(hits, ["reliability", "validity"], "any") is True
    assert metrics.keyword_hit(hits, ["reliability", "validity"], "all") is False
    assert metrics.keyword_hit(hits, ["reliability", "sampling"], "all") is True


def test_first_hit_rank_and_rr():
    hits = [_hit("intro"), _hit("about validity here")]
    assert metrics.first_hit_rank(hits, ["validity"]) == 2
    assert metrics.reciprocal_rank(hits, ["validity"]) == 0.5
    assert metrics.first_hit_rank(hits, ["nope"]) is None


# ---- safety + marking suites ----

def test_safety_suite_all_pass(settings, db):
    result = run_safety(settings)
    assert result["passed"] == result["total"]
    assert result["total"] >= 5


def test_marking_consistency_passes():
    result = run_marking_consistency()
    assert result["passed"] == result["total"]


# ---- retrieval suite (offline) ----

def test_retrieval_eval_runs(settings, db):
    settings.embeddings.provider = "hash"
    settings.embeddings.hash_dim = 128
    ingest(settings)
    index_embeddings(settings)
    dataset = {
        "course": "REIT6811",
        "queries": [
            {"id": "rel", "query": "reliability", "expected_keywords": ["reliability"]},
        ],
    }
    report = run_retrieval(settings, dataset=dataset, k=5)
    assert report["count"] == 1
    assert report["recall_any_at_k"] == 1.0
    assert report["queries"][0]["any_hit"] is True
