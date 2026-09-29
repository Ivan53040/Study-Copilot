"""Human-labelled answer grounding metrics.

Each substantive answer claim is labelled for support in the source material and
whether the cited page actually supports it. Citation IDs alone are insufficient.
"""

from __future__ import annotations


def score_claims(claims: list[dict]) -> dict[str, float]:
    if not claims:
        raise ValueError("At least one substantive claim must be labelled")
    cited = [claim for claim in claims if claim["cited"]]
    return {
        "answer_faithfulness": sum(bool(c["supported"]) for c in claims) / len(claims),
        "citation_accuracy": (
            sum(bool(c["citation_correct"]) for c in cited) / len(cited)
            if cited else 0.0
        ),
        "citation_coverage": len(cited) / len(claims),
    }
