"""Submit the wedding-v1 fixed test set to a running local server.

Usage:
    .\.venv\Scripts\python.exe testsets\wedding-v1\run_testset.py --limit 3
    .\.venv\Scripts\python.exe testsets\wedding-v1\run_testset.py --ids WED-001,WED-007
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import httpx


BASE_DIR = Path(__file__).resolve().parent
TESTSET_PATH = BASE_DIR / "testset.json"
SUBMITTED_PATH = BASE_DIR / "submitted-tasks.csv"


def load_testset() -> dict[str, Any]:
    with TESTSET_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def upload_image(client: httpx.Client, server: str, path: Path) -> str:
    with path.open("rb") as file:
        response = client.post(
            f"{server}/api/upload",
            files={"file": (path.name, file, "image/png")},
            timeout=120,
        )
    response.raise_for_status()
    data = response.json()
    file_id = data.get("file_id") or data.get("file_path")
    if not file_id:
        raise RuntimeError(f"Upload response missing file id: {data}")
    return str(file_id)


def resolve_asset(testset: dict[str, Any], group: str, key: str | None) -> Path | None:
    if not key:
        return None
    relative = testset["assets"][group][key]
    return BASE_DIR / relative


def select_scenarios(testset: dict[str, Any], ids: str | None, limit: int | None) -> list[dict[str, Any]]:
    scenarios = list(testset["scenarios"])
    if ids:
        wanted = {item.strip() for item in ids.split(",") if item.strip()}
        scenarios = [item for item in scenarios if item["id"] in wanted]
    if limit:
        scenarios = scenarios[:limit]
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--ids", help="Comma-separated scenario ids, for example WED-001,WED-007")
    parser.add_argument("--limit", type=int, help="Submit only the first N scenarios")
    parser.add_argument("--dry-run", action="store_true", help="Print selected scenarios without API calls")
    args = parser.parse_args()

    server = args.server.rstrip("/")
    testset = load_testset()
    scenarios = select_scenarios(testset, args.ids, args.limit)

    if not scenarios:
        raise SystemExit("No scenarios selected.")

    if args.dry_run:
        for item in scenarios:
            print(f"{item['id']} {item['name']}")
        return

    rows: list[dict[str, str]] = []
    with httpx.Client() as client:
        health = client.get(f"{server}/api/health", timeout=30)
        health.raise_for_status()

        for scenario in scenarios:
            model_path = resolve_asset(testset, "models", scenario["model"])
            dress_path = resolve_asset(testset, "dresses", scenario["dress"])
            pose_path = resolve_asset(testset, "pose_refs", scenario.get("pose_ref"))

            if model_path is None or dress_path is None:
                raise RuntimeError(f"{scenario['id']} missing required model or dress")

            model_file = upload_image(client, server, model_path)
            dress_file = upload_image(client, server, dress_path)
            pose_file = upload_image(client, server, pose_path) if pose_path else None

            payload = {
                "name": f"{scenario['id']} {scenario['name']}",
                "model_file": model_file,
                "dress_file": dress_file,
                "pose_reference_file": pose_file,
                "clothing_type": "wedding_gown",
                "scene": scenario["scene"],
                "scene_prompt": scenario.get("scene_prompt") or "",
                "resolution": scenario["resolution"],
                "face_swap": False,
                "pose": scenario["pose"],
                "pose_mode": scenario["pose_mode"],
                "preserve_face": True,
                "generation_mode": "stable",
            }
            response = client.post(f"{server}/api/create-task", json=payload, timeout=120)
            response.raise_for_status()
            data = response.json()
            task_id = str(data["task_id"])
            rows.append(
                {
                    "scenario_id": scenario["id"],
                    "task_id": task_id,
                    "name": scenario["name"],
                    "risk": scenario["risk"],
                }
            )
            print(f"{scenario['id']} -> {task_id}")

    with SUBMITTED_PATH.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["scenario_id", "task_id", "name", "risk"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {SUBMITTED_PATH}")


if __name__ == "__main__":
    main()
