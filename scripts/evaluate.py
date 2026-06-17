"""CLI: run the evaluation suite and write a report.

Usage:
    python -m scripts.evaluate            # writes evals/report.md + .json
    python -m scripts.evaluate --k 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.database.db import init_db
from evals.report import render_markdown
from evals.runner import run_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation suite.")
    parser.add_argument("--k", type=int, default=5, help="top-k for retrieval")
    args = parser.parse_args()

    init_db()
    report = run_all(k=args.k)

    out_dir = Path(__file__).resolve().parents[1] / "evals"
    (out_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    md = render_markdown(report)
    (out_dir / "report.md").write_text(md, encoding="utf-8")

    r, s, m = report["retrieval"], report["safety"], report["marking"]
    print(
        f"Retrieval recall@{r['k']} (any): {r['recall_any_at_k']} | "
        f"MRR: {r['mrr']} | "
        f"Safety: {s['passed']}/{s['total']} | "
        f"Marking: {m['passed']}/{m['total']}"
    )
    print(f"Report written to {out_dir / 'report.md'}")


if __name__ == "__main__":
    main()
