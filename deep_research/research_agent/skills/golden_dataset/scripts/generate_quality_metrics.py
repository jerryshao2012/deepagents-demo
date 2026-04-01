#!/usr/bin/env python3
"""Append judge-model quality metrics to a golden dataset CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_agent.skills.golden_dataset.scripts.golden_dataset_metrics import score_dataset_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Similarity, Relevance, Coherence, and Groundedness columns for a golden dataset CSV.",
    )
    parser.add_argument("input_csv", help="Path to the input CSV with at least Question and Answer columns.")
    parser.add_argument(
        "--output-csv",
        help="Path to write the enriched CSV. Defaults to <input>-with-metrics.csv.",
    )
    return parser


def default_output_path(input_csv: str) -> str:
    input_path = Path(input_csv)
    return str(input_path.with_name(f"{input_path.stem}-with-metrics{input_path.suffix}"))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    output_csv = args.output_csv or default_output_path(args.input_csv)
    result = score_dataset_file(args.input_csv, output_csv)
    print(f"Wrote scored dataset to {result}")


if __name__ == "__main__":
    main()
