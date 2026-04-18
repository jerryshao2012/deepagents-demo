"""Golden Dataset Skill Package.

This package contains utilities for golden dataset generation and evaluation:
- pipeline.py: CSV export and quality metrics evaluation
- scripts/: Metric calculation and report generation scripts
"""

from .pipeline import (
    GOLDEN_DATASET_TARGET_ID,
    evaluate_and_report_golden_dataset,
    evaluate_golden_dataset_csv_file,
    export_golden_dataset_csv,
    normalize_golden_item_ids,
)

__all__ = [
    "GOLDEN_DATASET_TARGET_ID",
    "normalize_golden_item_ids",
    "export_golden_dataset_csv",
    "evaluate_golden_dataset_csv_file",
    "evaluate_and_report_golden_dataset",
]
