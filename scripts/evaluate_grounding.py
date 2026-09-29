"""Score manually labelled answer claims and citations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.grounding_metrics import score_claims


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", help="JSON file with answers[].claims[] labels")
    args = parser.parse_args()
    data = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    rows = [
        {"id": item["id"], **score_claims(item["claims"])}
        for item in data["answers"]
    ]
    all_claims = [claim for item in data["answers"] for claim in item["claims"]]
    overall = score_claims(all_claims)
    print(json.dumps({"answers": rows, "overall": overall}, indent=2))


if __name__ == "__main__":
    main()
