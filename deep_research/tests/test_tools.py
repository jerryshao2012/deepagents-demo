from pathlib import Path

from langchain_core.messages import HumanMessage

from agent import ResearchStateMiddleware
from research_agent import tools
from research_agent.tools import (
    fetch_webpage_content,
)
from research_agent.tools import (
    finalize_golden_dataset_output,
    read_doc_folder,
)
from research_agent.utils.skill_registry import get_skill_registry


def test_get_skill_definition_reports_schema_validation_errors() -> None:
    result = get_skill_registry().get_skill_definition.invoke(
        {
            "skill_id": "golden-dataset",
            "payload_json": "{\"items\": [{\"id\": \"Q1\", \"coverage_area\": \"General\", \"question\": \"Q?\"}]}",
        }
    )

    assert "Schema validation failed" in result


def test_get_skill_definition_rejects_missing_required_fields() -> None:
    result = get_skill_registry().get_skill_definition.invoke(
        {
            "skill_id": "golden-dataset",
            "payload_json": """
            {
              "items": [
                {
                  "id": "Q1",
                  "coverage_area": "Leave",
                  "question": "How do I request parental leave?"
                }
              ]
            }
            """
        }
    )

    assert "Schema validation failed" in result
    assert "answer" in result


def test_get_skill_definition_uses_declarative_render_spec(tmp_path, monkeypatch) -> None:
    from research_agent.utils import skill_registry

    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: demo
title: Demo Target
description: Demo skill for declarative rendering
render_template: markdown_blocks
---

## Instructions

Return the final result by calling `render_skill_output`.

## Schema

```json
{
  "type": "object",
  "required": ["topic", "items"],
  "properties": {
    "topic": {"type": "string"},
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "minutes"],
        "properties": {
          "name": {"type": "string"},
          "minutes": {"type": "integer"}
        }
      }
    }
  }
}
```

## Render Spec

```json
[
  {"type": "heading", "level": 1, "value": "Demo: {topic}"},
  {"type": "repeat", "path": "items", "body": [
    {"type": "heading", "level": 2, "value": "Item {index}: {item.name}"},
    {"type": "text", "value": "Minutes: {item.minutes}"}
  ]},
  {"type": "text", "value": "Total: {sum(items[].minutes)}"}
]
```
""",
        encoding="utf-8",
    )

    registry = skill_registry.SkillRegistry(tmp_path / "skills")
    monkeypatch.setattr(skill_registry, "_get_global_registry", lambda: registry)

    result = get_skill_registry().get_skill_definition.invoke(
        {
            "skill_id": "demo",
            "payload_json": """
            {
              "topic": "Agenda",
              "items": [
                {"name": "Intro", "minutes": 5},
                {"name": "Deep Dive", "minutes": 15}
              ]
            }
            """
        }
    )

    assert "# Demo: Agenda" in result
    assert "## Item 1: Intro" in result
    assert "Minutes: 15" in result
    assert "Total: 20" in result


def test_get_skill_definition_reports_unknown_skill() -> None:
    result = get_skill_registry().get_skill_definition.invoke(
        {
            "skill_id": "does-not-exist",
            "payload_json": "{}",
        }
    )

    assert "Unknown skill" in result


def test_get_skill_definition_renders_golden_dataset_without_metric_fields() -> None:
    result = get_skill_registry().get_skill_definition.invoke(
        {
            "skill_id": "golden-dataset",
            "payload_json": """
            {
              "dataset_name": "HR Policy Starter",
              "domain": "Employee handbook and HR policy",
              "recommended_total_dataset_size": 150,
              "coverage_areas": ["Leave", "Benefits"],
              "items": [
                {
                  "id": "Q1",
                  "coverage_area": "Leave",
                  "question": "How do I request parental leave under the employee handbook?",
                  "answer": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
                  "content": "The employee handbook leave section explains eligibility, notice periods, and HR approval steps."
                }
              ]
            }
            """,
        }
    )

    assert "# Golden Dataset Starter: HR Policy Starter" in result
    assert "## Coverage Areas" in result
    assert "### Q1. Leave" in result
    assert "Question: How do I request parental leave under the employee handbook?" in result
    assert "Answer:" in result
    assert "Content:" in result
    assert "QnA Similarity Evaluation" not in result
    assert "QnA Groundedness Evaluation" not in result


def test_finalize_golden_dataset_output_exports_content_to_csv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path))

    def fake_evaluate_and_report(csv_path, payload, output_folder, elapsed_seconds=None):
        from pathlib import Path
        metrics_csv = Path(str(csv_path).replace(".csv", "-with-metrics.csv"))
        metrics_csv.write_text(
            "ID,Coverage Area,Question,Answer,Content,Similarity,Relevance,Coherence,Groundedness\nQ1,Leave,How?,Answer.,Content.,3,75,4,3\n",
            encoding="utf-8")
        markdown_content = "| ID | Question | Answer | Similarity | Relevance | Coherence | Groundedness |\n|----|----------|--------|------------|-----------|-----------|--------------|\n| Q1 | How? | Answer. | 3 | 75 | 4 | 3 |"
        final_report = "# Report\n\nTest report content"
        return metrics_csv, markdown_content, final_report

    monkeypatch.setattr(
        "research_agent.skills.golden_dataset.pipeline.evaluate_and_report_golden_dataset",
        fake_evaluate_and_report,
    )

    result = finalize_golden_dataset_output.invoke(
        {
            "payload_json": """
            {
              "dataset_name": "HR Policy Starter",
              "domain": "Employee handbook and HR policy",
              "recommended_total_dataset_size": 150,
              "coverage_areas": ["Leave"],
              "items": [
                {
                  "id": "Q1",
                  "coverage_area": "Leave",
                  "question": "How do I request parental leave under the employee handbook?",
                  "answer": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
                  "content": "The handbook explains eligibility, notice periods, and HR approval steps."
                }
              ]
            }
            """,
        }
    )

    assert "CSV exported to" in result
    csv_path = tmp_path / "hr_policy_starter.csv"
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Content" in csv_text
    assert "eligibility, notice periods, and HR approval steps" in csv_text
    assert "Context" not in csv_text
    # Check that new files are generated
    assert (tmp_path / "golden_dataset_metrics.md").exists()
    assert (tmp_path / "final_report.md").exists()


def test_finalize_golden_dataset_output_runs_metrics(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path))

    def fake_evaluate_and_report(csv_path, payload, output_folder, elapsed_seconds=None):
        from pathlib import Path
        metrics_csv = Path(str(csv_path).replace(".csv", "-with-metrics.csv"))
        metrics_csv.write_text("scored content", encoding="utf-8")
        markdown_content = "| Metric | Value |\n|--------|-------|\n| Test | 1 |"
        final_report = "# Final Report\n\nComplete report"
        return metrics_csv, markdown_content, final_report

    monkeypatch.setattr(
        "research_agent.skills.golden_dataset.pipeline.evaluate_and_report_golden_dataset",
        fake_evaluate_and_report,
    )

    result = finalize_golden_dataset_output.invoke(
        {
            "payload_json": """
            {
              "dataset_name": "HR Policy Starter",
              "domain": "Employee handbook and HR policy",
              "recommended_total_dataset_size": 150,
              "coverage_areas": ["Leave"],
              "items": [
                {
                  "id": "Q1",
                  "coverage_area": "Leave",
                  "question": "How do I request parental leave under the employee handbook?",
                  "answer": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
                  "content": "The handbook explains eligibility, notice periods, and HR approval steps."
                }
              ]
            }
            """,
        }
    )

    assert "CSV exported to" in result
    assert "Metrics CSV:" in result
    assert "Metrics Markdown:" in result
    assert "Final Report:" in result
    csv_path = tmp_path / "hr_policy_starter.csv"
    assert csv_path.exists()
    metrics_csv_path = tmp_path / "hr_policy_starter-with-metrics.csv"
    assert metrics_csv_path.exists()
    assert metrics_csv_path.read_text() == "scored content"
    # Verify new files exist
    assert (tmp_path / "golden_dataset_metrics.md").exists()
    assert (tmp_path / "final_report.md").exists()


def test_finalize_golden_dataset_output_updates_state_with_text_file_data(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path))

    def fake_evaluate_and_report(csv_path, payload, output_folder, elapsed_seconds=None):
        from pathlib import Path

        metrics_csv = Path(str(csv_path).replace(".csv", "-with-metrics.csv"))
        metrics_csv.write_text("scored content", encoding="utf-8")
        markdown_content = "| Metric | Value |\n|--------|-------|\n| Test | 1 |"
        final_report = "# Final Report\n\nComplete report"
        return metrics_csv, markdown_content, final_report

    monkeypatch.setattr(
        "research_agent.skills.golden_dataset.pipeline.evaluate_and_report_golden_dataset",
        fake_evaluate_and_report,
    )

    state = {"files": {}, "skill": "golden-dataset"}

    result = finalize_golden_dataset_output.func(
        payload_json="""
        {
          "dataset_name": "HR Policy Starter",
          "domain": "Employee handbook and HR policy",
          "recommended_total_dataset_size": 150,
          "coverage_areas": ["Leave"],
          "items": [
            {
              "id": "Q1",
              "coverage_area": "Leave",
              "question": "How do I request parental leave under the employee handbook?",
              "answer": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
              "content": "The handbook explains eligibility, notice periods, and HR approval steps."
            }
          ]
        }
        """,
        state=state,
    )

    assert "All files have been generated successfully!" in result
    assert state["files"]["/golden_dataset_metrics.md"]["content"] == [
        "| Metric | Value |",
        "|--------|-------|",
        "| Test | 1 |",
    ]
    assert state["files"]["/final_report.md"]["content"] == [
        "# Final Report",
        "",
        "Complete report",
    ]


def test_read_doc_folder_reads_text_and_markdown_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path / "output"))
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "summary.md").write_text("# heading", encoding="utf-8")

    result = read_doc_folder.func(
        folder_path=str(tmp_path),
        state={"doc_folder": str(tmp_path)}
    )

    assert "Content of notes.txt" in result
    assert "alpha" in result
    assert "Content of summary.md" in result
    assert "# heading" in result


def test_read_doc_folder_reports_unsupported_and_empty_cases(tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"png")

    result = read_doc_folder.func(
        folder_path=str(tmp_path),
        state={"doc_folder": str(tmp_path)}
    )

    assert "No supported document files found" in result


def test_read_file_impl_returns_structured_preview_for_large_markdown(tmp_path: Path) -> None:
    large_doc = tmp_path / "policy.md"
    repeated_section = (
        "## Liability Coverage\n"
        "This section explains liability coverage, claim handling, deductibles, and exclusions.\n\n"
    )
    large_doc.write_text(
        "# Ontario Automobile Policy\n\n"
        + repeated_section * 600,
        encoding="utf-8",
    )

    result = tools.read_file_impl(str(large_doc), state={})

    assert "returning a structured preview" in result
    assert "Heading outline" in result
    assert "## Liability Coverage" in result
    assert len(result) < 20000
    assert "Section chunks:" in result


def test_read_file_impl_can_target_specific_markdown_section(tmp_path: Path) -> None:
    policy_doc = tmp_path / "policy.md"
    policy_doc.write_text(
        "# Ontario Automobile Policy\n\n"
        "## Section 3 - Liability Coverage\n"
        "Liability coverage protects you when you are at fault.\n\n"
        "## Section 4 - Accident Benefits Coverage\n"
        "Accident benefits may be available regardless of fault.\n",
        encoding="utf-8",
    )

    result = tools.read_file_impl(
        f"{policy_doc}#Section 4 - Accident Benefits Coverage",
        state={},
    )

    assert "Section 4 - Accident Benefits Coverage" in result
    assert "Accident benefits may be available regardless of fault." in result
    assert "Liability coverage protects you when you are at fault." not in result


def test_read_file_impl_reports_unknown_markdown_section(tmp_path: Path) -> None:
    policy_doc = tmp_path / "policy.md"
    policy_doc.write_text(
        "# Ontario Automobile Policy\n\n"
        "## Section 3 - Liability Coverage\n"
        "Liability coverage protects you when you are at fault.\n",
        encoding="utf-8",
    )

    result = tools.read_file_impl(
        f"{policy_doc}#Section 9 - Missing Section",
        state={},
    )

    assert "Section 'Section 9 - Missing Section' not found" in result
    assert "Available sections:" in result


def test_research_state_middleware_seeds_research_request_file() -> None:
    middleware = ResearchStateMiddleware()

    result = middleware.before_agent(
        state={"messages": [HumanMessage(content="Generate 5 Q/A pairs from ./docs/policy/")]},
        runtime=None,
    )

    assert result is not None
    assert "/research_request.md" in result["files"]
    assert "Generate 5 Q/A pairs" in "".join(result["files"]["/research_request.md"]["content"])


def test_ls_lists_files_and_directories(tmp_path: Path) -> None:
    (tmp_path / "file1.txt").touch()
    (tmp_path / "dir1").mkdir()
    (tmp_path / "dir1" / "file2.txt").touch()

    result = tools.ls.invoke({"path": str(tmp_path)})

    assert "file1.txt" in result
    assert "dir1/" in result
    assert "file2.txt" not in result


def test_ls_handles_nonexistent_path(tmp_path: Path) -> None:
    result = tools.ls.invoke({"path": str(tmp_path / "nonexistent")})
    assert "Error: Path" in result
    assert "not found" in result


def test_glob_finds_files_matching_pattern(tmp_path: Path) -> None:
    (tmp_path / "test1.md").touch()
    (tmp_path / "test2.md").touch()
    (tmp_path / "other.txt").touch()
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "test3.md").touch()

    # Simple glob
    result = tools.glob.invoke({"pattern": f"{tmp_path}/*.md"})
    assert "test1.md" in result
    assert "test2.md" in result
    assert "other.txt" not in result
    assert "test3.md" not in result

    # Recursive glob
    result = tools.glob.invoke({"pattern": f"{tmp_path}/**/*.md"})
    assert "test1.md" in result
    assert "test2.md" in result
    assert "test3.md" in result


def test_glob_handles_nonexistent_base_path() -> None:
    result = tools.glob.invoke({"pattern": "/nonexistent/path/*.md"})
    assert "Error: Base path" in result


def test_finalize_golden_dataset_output_processes_payload(tmp_path, monkeypatch) -> None:
    """finalize_golden_dataset_output works regardless of active skill (tool doesn't gate on skill state)."""
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path))

    result = finalize_golden_dataset_output.func(
        payload_json='{"items": [{"id": "Q1", "coverage_area": "General", "question": "Q?", "answer": "A"}]}',
        state={"skill": "humanizer"},
    )

    assert "Successfully exported" in result


def test_fetch_webpage_content_returns_markdown_for_valid_url() -> None:
    """Test that fetch_webpage_content can fetch and convert a webpage to markdown."""
    # Using a simple, reliable URL for testing
    result = fetch_webpage_content.invoke({"url": "https://example.com", "timeout": 5.0})

    # Should return markdown content, not an error
    assert not result.startswith("Error fetching content")
    assert len(result) > 0


def test_fetch_webpage_content_handles_invalid_url() -> None:
    """Test that fetch_webpage_content handles invalid URLs gracefully."""
    result = fetch_webpage_content.invoke({"url": "https://this-domain-does-not-exist-12345.com", "timeout": 2.0})

    # Should return an error message
    assert result.startswith("Error fetching content")


def test_fetch_webpage_content_has_proper_tool_metadata() -> None:
    """Test that fetch_webpage_content has proper tool metadata."""
    assert hasattr(fetch_webpage_content, "name")
    assert fetch_webpage_content.name == "fetch_webpage_content"
    assert hasattr(fetch_webpage_content, "description")
    assert "markdown" in fetch_webpage_content.description.lower()
