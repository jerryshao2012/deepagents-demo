from research_agent.skills.golden_dataset.scripts.generate_quality_metrics import build_parser


def test_generate_quality_metrics_parser_accepts_report_flag() -> None:
    parser = build_parser()

    args = parser.parse_args(["output/golden_dataset.csv", "--report"])

    assert args.input_csv == "output/golden_dataset.csv"
    assert args.report is True


def test_generate_quality_metrics_parser_mentions_content_report_file() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["output/golden_dataset.csv", "--report", "--report-file", "output/content-report.txt"]
    )

    assert args.report_file == "output/content-report.txt"
