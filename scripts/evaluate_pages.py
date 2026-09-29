"""Evaluate retrieval with manually labelled PDF/PPTX page judgments."""

from __future__ import annotations

import argparse
import json

from evals.page_benchmark import load_page_dataset, run_page_benchmark


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="JSON file with queries and relevant_pages")
    parser.add_argument("--k", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_page_benchmark(load_page_dataset(args.dataset), k=args.k), indent=2))


if __name__ == "__main__":
    main()
