"""Tests for quality metrics generation."""

from research_agent.skills.golden_dataset.scripts.generate_quality_metrics import build_parser

from research_agent.tools import reports_output_folder


def test_generate_quality_metrics_parser_accepts_report_flag() -> None:
    parser = build_parser()

    args = parser.parse_args([f"{reports_output_folder}/golden_dataset.csv", "--report"])

    assert args.input_csv == f"{reports_output_folder}/golden_dataset.csv"
    assert args.report is True


def test_generate_quality_metrics_parser_mentions_content_report_file() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [f"{reports_output_folder}/golden_dataset.csv", "--report", "--report-file",
         f"{reports_output_folder}/content-report.txt"]
    )

    assert args.report_file == f"{reports_output_folder}/content-report.txt"
