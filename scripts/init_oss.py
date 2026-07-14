"""Validate Alibaba Cloud OSS configuration with a small write/read/delete check."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.storage.object_storage import ObjectStorageConfig, create_object_storage


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify OSS storage for the Wedding AI Tool.")
    parser.add_argument(
        "--prefix",
        default="healthchecks",
        help="OSS key prefix for the temporary validation object.",
    )
    args = parser.parse_args()

    config = ObjectStorageConfig.from_settings()
    if (config.mode or "").lower() != "oss":
        print("ok=false")
        print("reason=OBJECT_STORAGE_MODE must be oss")
        return 2

    key = f"{args.prefix.strip('/')}/oss-check-{int(time.time())}.txt"
    content = b"wedding-ai-tool oss check\n"

    try:
        storage = create_object_storage(config)
        saved_key = storage.save_bytes(key, content, "text/plain")
        exists_after_write = storage.exists(saved_key)
        downloaded = storage.get_bytes(saved_key)
        public_url = storage.public_url(saved_key)
        deleted = storage.delete(saved_key)
        exists_after_delete = storage.exists(saved_key)
    except Exception as exc:
        print("ok=false")
        print(f"error_type={type(exc).__name__}")
        print(f"error={str(exc)}")
        return 1

    ok = exists_after_write and downloaded == content and deleted and not exists_after_delete
    print(f"ok={str(ok).lower()}")
    print(f"bucket={config.oss_bucket}")
    print(f"endpoint={config.oss_endpoint}")
    print(f"test_key={saved_key}")
    print(f"public_url={public_url}")
    print(f"deleted={str(deleted).lower()}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
