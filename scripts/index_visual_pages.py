"""Caption indexed PDF/PPTX pages with the configured visual-pages model."""

from __future__ import annotations

import argparse
import json

from app.ingestion.visual_pages import index_visual_pages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=int)
    parser.add_argument("--limit", type=int, default=20, help="Maximum new pages to try (default: 20)")
    args = parser.parse_args()
    report = index_visual_pages(document_id=args.document_id, limit=args.limit)
    print(json.dumps(report.as_dict(), indent=2))


if __name__ == "__main__":
    main()
