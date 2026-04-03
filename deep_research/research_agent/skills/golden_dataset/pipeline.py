"""CSV export and evaluation for the golden-dataset target."""

from __future__ import annotations

import csv
import re
from pathlib import Path

GOLDEN_DATASET_TARGET_ID = "golden-dataset"


def normalize_golden_item_ids(payload: dict) -> None:
    """Ensure each item has `id`, including legacy `ID` uppercase."""
    items = payload.get("items", [])
    for idx, item in enumerate(items, start=1):
        if not item.get("id") and not item.get("ID"):
            item["id"] = str(idx)
        elif item.get("ID") and not item.get("id"):
            item["id"] = item["ID"]


def export_golden_dataset_csv(payload: dict, output_folder: Path) -> Path:
    """Write golden dataset items to CSV under ``output_folder`` (mutates ``payload`` items for ids)."""
    normalize_golden_item_ids(payload)
    items = payload.get("items", [])
    filename = (
        re.sub(r"[^a-zA-Z0-9_\- ]", "", payload.get("dataset_name", "dataset"))
        .strip()
        .replace(" ", "_")
        .lower()
    )
    if not filename:
        filename = "golden_dataset"

    output_folder.mkdir(parents=True, exist_ok=True)
    csv_path = output_folder / f"{filename}.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Coverage Area", "Question", "Answer", "Content"])
        for item in items:
            writer.writerow(
                [
                    item.get("id", ""),
                    item.get("coverage_area", ""),
                    item.get("question", ""),
                    item.get("answer", ""),
                    item.get("content", ""),
                ]
            )
    return csv_path


def evaluate_golden_dataset_csv_file(file_path: str) -> str:
    """Run quality metrics on a golden-dataset CSV; same behavior as `trigger_dataset_evaluation`."""
    path_obj = Path(file_path)
    if not path_obj.exists():
        return f"File not found: {file_path}"

    try:
        from research_agent.skills.golden_dataset.scripts.golden_dataset_metrics import (
            score_dataset_file,
        )

        output_csv = str(path_obj.with_name(f"{path_obj.stem}-with-metrics{path_obj.suffix}"))
        result_path = score_dataset_file(str(path_obj), output_csv)
        return f"Successfully evaluated dataset. Metrics saved to: {result_path}"
    except Exception as exc:
        return f"Failed to run metric evaluation: {exc}"
