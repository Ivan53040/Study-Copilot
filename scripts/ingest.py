"""CLI: run a full incremental ingest of all approved sources.

Usage:
    python -m scripts.ingest            # ingest everything in config
    python -m scripts.ingest --course REIT6811
"""

from __future__ import annotations

import argparse
import json

from app.database.db import init_db
from app.ingestion.service import ingest


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest study materials.")
    parser.add_argument("--course", default=None, help="Optional course filter")
    args = parser.parse_args()

    init_db()
    report = ingest(course=args.course)
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
