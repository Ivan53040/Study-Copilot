"""CLI: compute and store chunk embeddings for vector search.

Usage:
    python -m scripts.embed              # embed chunks missing an embedding
    python -m scripts.embed --reindex    # re-embed everything
"""

from __future__ import annotations

import argparse
import json

from app.database.db import init_db
from app.retrieval.indexing import index_embeddings


def main() -> None:
    parser = argparse.ArgumentParser(description="Index chunk embeddings.")
    parser.add_argument("--reindex", action="store_true", help="Re-embed all chunks")
    args = parser.parse_args()

    init_db()
    report = index_embeddings(reindex=args.reindex)
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
