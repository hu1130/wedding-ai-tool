"""Initialize and verify the Wedding AI Tool business database."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import load_env_files
from backend.storage import database


def main() -> int:
    load_env_files()
    parser = argparse.ArgumentParser(
        description="Create and verify business tables for the Wedding AI Tool."
    )
    parser.add_argument(
        "--allow-sqlite",
        action="store_true",
        help="Allow the local SQLite fallback. Production should not use this.",
    )
    args = parser.parse_args()

    url = database.resolve_database_url()
    is_mysql = database.is_mysql_url(url)
    if not is_mysql and not args.allow_sqlite:
        print("Refusing to initialize non-MySQL database without --allow-sqlite.")
        print("Set DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/DB?charset=utf8mb4")
        return 2

    status = database.schema_status()
    print(f"database={status['database']}")
    print(f"ok={str(status['ok']).lower()}")
    print("expected_tables=" + ",".join(status["expected_tables"]))
    if status["missing_tables"]:
        print("missing_tables=" + ",".join(status["missing_tables"]))
        return 1
    print("missing_tables=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
