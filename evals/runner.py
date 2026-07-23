"""Run the evaluation suites and aggregate results."""

from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import Settings, get_settings
from app.generation.marking import _heuristic_short, grade_mcq
from app.retrieval.service import search
from app.retrieval.types import MetadataFilter
from app.security.paths import is_readable, is_writable
from evals import metrics

DATASET_PATH = Path(__file__).with_name("retrieval_dataset.json")


def load_dataset(path: Path | None = None) -> dict:
    path = path or DATASET_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def run_retrieval(
    settings: Settings | None = None,
    *,
    dataset: dict | None = None,
    k: int = 5,
) -> dict:
    settings = settings or get_settings()
    dataset = dataset or load_dataset()
    course = dataset.get("course")

    rows = []
    any_hits, all_hits, rrs = [], [], []
    used_vector = False
    for q in dataset["queries"]:
        resp = search(
            q["query"],
            settings=settings,
            flt=MetadataFilter(course=course),
            final_limit=k,
        )
        used_vector = used_vector or resp.used_vector
        kws = q["expected_keywords"]
        any_hit = metrics.keyword_hit(resp.hits, kws, "any")
        all_hit = metrics.keyword_hit(resp.hits, kws, "all")
        rr = metrics.reciprocal_rank(resp.hits, kws)
        any_hits.append(1.0 if any_hit else 0.0)
        all_hits.append(1.0 if all_hit else 0.0)
        rrs.append(rr)
        rows.append(
            {
                "id": q["id"],
                "query": q["query"],
                "any_hit": any_hit,
                "all_hit": all_hit,
                "first_rank": metrics.first_hit_rank(resp.hits, kws),
                "top_title": resp.hits[0].title if resp.hits else None,
            }
        )

    return {
        "k": k,
        "count": len(rows),
        "used_vector": used_vector,
        "recall_any_at_k": round(metrics.mean(any_hits), 3),
        "recall_all_at_k": round(metrics.mean(all_hits), 3),
        "mrr": round(metrics.mean(rrs), 3),
        "queries": rows,
    }


def run_safety(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    root = Path(settings.vault.root)
    out = settings.output_root

    checks = [
        ("write allowed inside StudyCopilot",
         is_writable(out / "Generated Notes" / "x.md", settings) is True),
        ("write blocked outside StudyCopilot",
         is_writable(root / "SAMPLE101 - Research Methods" / "x.md", settings) is False),
        ("path traversal out of StudyCopilot blocked",
         is_writable(out / ".." / ".." / "x.md", settings) is False),
        (".env not readable",
         is_readable(root / ".env", settings) is False),
        (".obsidian not readable",
         is_readable(root / ".obsidian" / "config.json", settings) is False),
    ]
    results = [{"name": n, "passed": bool(p)} for n, p in checks]
    return {
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        "checks": results,
    }


def run_marking_consistency() -> dict:
    """Marking must be deterministic for the same input (regression guard)."""
    opts = ["consistency", "accuracy", "bias", "sampling"]
    mcq_runs = {grade_mcq("consistency", "consistency", opts) for _ in range(5)}
    short_runs = {
        _heuristic_short("reliability is consistency of measurement",
                         "consistency of measurement reliability")
        for _ in range(5)
    }
    checks = [
        {"name": "MCQ grading deterministic", "passed": mcq_runs == {"correct"}},
        {"name": "short grading deterministic", "passed": len(short_runs) == 1},
    ]
    return {
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
        "checks": checks,
    }


def run_all(settings: Settings | None = None, *, k: int = 5) -> dict:
    settings = settings or get_settings()
    return {
        "retrieval": run_retrieval(settings, k=k),
        "safety": run_safety(settings),
        "marking": run_marking_consistency(),
    }
