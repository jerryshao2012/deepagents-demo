from pathlib import Path

from research_agent_cli import append_dataset_evaluation_result, derive_output_folder


def test_derive_output_folder_uses_final_doc_folder_segment() -> None:
    assert derive_output_folder("./doc/policy") == Path("output") / "policy"
    assert derive_output_folder("./docs/policy") == Path("output") / "policy"


def test_append_dataset_evaluation_result_runs_when_csv_export_is_present(monkeypatch) -> None:
    def fake_run_dataset_evaluation(file_path: str) -> str:
        assert file_path == "output/policy/bank_policy.csv"
        return "Successfully evaluated dataset. Metrics saved to: output/policy/bank_policy-with-metrics.csv"

    monkeypatch.setattr("research_agent_cli.run_dataset_evaluation", fake_run_dataset_evaluation)

    content = "# Golden Dataset\n\n**CSV exported to:** `output/policy/bank_policy.csv`"

    updated = append_dataset_evaluation_result(content)

    assert "Metrics saved to: output/policy/bank_policy-with-metrics.csv" in updated


def test_append_dataset_evaluation_result_leaves_content_unchanged_without_csv_export() -> None:
    content = "# Not a golden dataset"

    assert append_dataset_evaluation_result(content) == content
