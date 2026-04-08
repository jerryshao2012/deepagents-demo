from research_agent.skills.golden_dataset.scripts.generate_quality_metrics import build_parser
from research_agent.tools import REPORTS_OUTPUT_FOLDER


def test_generate_quality_metrics_parser_accepts_report_flag() -> None:
    parser = build_parser()

    args = parser.parse_args([f"{REPORTS_OUTPUT_FOLDER}/golden_dataset.csv", "--report"])

    assert args.input_csv == f"{REPORTS_OUTPUT_FOLDER}/golden_dataset.csv"
    assert args.report is True


def test_generate_quality_metrics_parser_mentions_content_report_file() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [f"{REPORTS_OUTPUT_FOLDER}/golden_dataset.csv", "--report", "--report-file",
         f"{REPORTS_OUTPUT_FOLDER}/content-report.txt"]
    )

    assert args.report_file == f"{REPORTS_OUTPUT_FOLDER}/content-report.txt"
