import datetime
import json
import os


def create_collection_snapshot(root_key: str) -> dict:
    """
    Create the base JSON snapshot structure for the DJ set collection export.
    """
    return {
        "generated_at": datetime.now(datetime.timezone.utc).isoformat(),
        root_key: [],
    }


def write_json_snapshot(snapshot: dict, json_output_path: str) -> None:
    """
    Write a JSON snapshot to disk, creating parent directories if needed.
    """
    os.makedirs(os.path.dirname(json_output_path) or ".", exist_ok=True)
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
