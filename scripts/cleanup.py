"""Run storage retention cleanup.

Dry-run is the default. Use --apply to delete, and keep CLEANUP_ENABLED=true in
production so scheduled cleanup cannot accidentally mutate local development.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.cleanup import run_cleanup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean expired uploads, outputs, and deleted records.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete planned items. Without this flag the command is a dry-run.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow deletion even when CLEANUP_ENABLED is false.",
    )
    args = parser.parse_args()

    result = run_cleanup(dry_run=not args.apply, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
