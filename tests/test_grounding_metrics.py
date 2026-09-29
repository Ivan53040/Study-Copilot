from __future__ import annotations

from evals.grounding_metrics import score_claims


def test_grounding_metrics_check_claim_support_and_actual_citation():
    scores = score_claims([
        {"supported": True, "cited": True, "citation_correct": True},
        {"supported": True, "cited": True, "citation_correct": False},
        {"supported": False, "cited": False, "citation_correct": False},
    ])
    assert scores == {
        "answer_faithfulness": 2 / 3,
        "citation_accuracy": 0.5,
        "citation_coverage": 2 / 3,
    }
