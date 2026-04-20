"""CSV export and evaluation for the golden-dataset skill."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from research_agent.skills.golden_dataset.scripts.golden_dataset_metrics import (
    convert_csv_to_markdown,
    generate_golden_dataset_report,
    score_dataset_file,
)
from research_agent.skills.golden_dataset.scripts.humanize_report import (
    humanize_report,
)

GOLDEN_DATASET_SKILL_ID = "golden-dataset"


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


def evaluate_golden_dataset_csv_file(file_path: str) -> tuple[Path, str]:
    """Run quality metrics on a golden-dataset CSV; same behavior as `trigger_dataset_evaluation`."""
    path_obj = Path(file_path)
    if not path_obj.exists():
        return Path(file_path), f"Error: File not found: {file_path}"

    output_csv = str(path_obj.with_name(f"{path_obj.stem}-with-metrics{path_obj.suffix}"))
    metrics_csv_path = score_dataset_file(str(path_obj), output_csv)

    # Step 2: Convert metrics CSV to markdown table
    markdown_content = convert_csv_to_markdown(str(metrics_csv_path))
    return metrics_csv_path, markdown_content


def evaluate_and_report_golden_dataset(
        csv_path: Path,
        payload: dict,
        elapsed_seconds: float = 0.0
) -> tuple[Path, str, str]:
    """Evaluate golden dataset CSV and generate both metrics markdown and final report.
    
    Args:
        csv_path: Path to the original CSV file.
        payload: The golden dataset payload with metadata.
        elapsed_seconds: Total time spent in agent chat (in seconds).
        
    Returns:
        Tuple of (metrics_csv_path, markdown_content, final_report_content).
    """
    # Step 1: Run quality metrics
    metrics_csv_path_str = str(csv_path.with_name(f"{csv_path.stem}-with-metrics{csv_path.suffix}"))
    metrics_csv_path = Path(score_dataset_file(str(csv_path), metrics_csv_path_str))

    # Step 2: Convert metrics CSV to markdown table
    markdown_content = convert_csv_to_markdown(str(metrics_csv_path))

    # Step 3: Generate comprehensive final report
    final_report_content = generate_golden_dataset_report(
        csv_path=str(csv_path),
        metrics_csv_path=str(metrics_csv_path),
        markdown_content=markdown_content,
        payload=payload,
        elapsed_seconds=elapsed_seconds
    )

    # Step 4: Humanize the report to remove AI writing patterns
    final_report_content = humanize_report(final_report_content)

    return metrics_csv_path, markdown_content, final_report_content
