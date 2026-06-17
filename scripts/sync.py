"""CLI: manually mirror the local vault to iCloud.

Usage:
    python -m scripts.sync            # perform the sync
    python -m scripts.sync --dry-run  # show what would change, change nothing
"""

from __future__ import annotations

import argparse
import json

from app.sync.service import run_sync


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync local vault <-> iCloud.")
    parser.add_argument("--dry-run", action="store_true", help="List changes only")
    args = parser.parse_args()

    result = run_sync(dry_run=args.dry_run)
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
