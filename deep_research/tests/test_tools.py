from pathlib import Path

from research_agent import tools
from research_agent.tools import (
    finalize_golden_dataset_output,
    frontend_slides,
    read_doc_folder,
    render_target_output,
)


def test_render_target_output_renders_slides_from_definition() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "study-slides",
            "payload_json": """
            {
              "topic": "AI Agents",
              "slides": [
                {
                  "title": "What Matters",
                  "bullets": ["Agents plan work", "Agents use tools"],
                  "speaker_notes": "Keep this high level."
                },
                {
                  "title": "What To Practice",
                  "bullets": ["Ground outputs in sources"],
                  "speaker_notes": "Close with next steps."
                }
              ]
            }
            """
        }
    )

    assert result.startswith("# Presentation: AI Agents")
    assert result.count("## Slide") == 2
    assert "### Speaking Notes" in result


def test_render_target_output_formats_45_minute_interview_kit() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "interview",
            "payload_json": """
            {
              "topic": "AI Agents",
              "objective": "Assess practical agent design judgment.",
              "questions": [
                {
                  "question": "How would you ground an agent in local documents?",
                  "timebox_minutes": 10,
                  "potential_answer": "A strong answer would cover retrieval, source selection, and citation strategy.",
                  "follow_up": "What trade-offs would you watch for?"
                }
              ]
            }
            """
        }
    )

    assert "# Interview Kit: AI Agents" in result
    assert "45-minute interview objective" in result
    assert "Timebox: 10 minutes" in result
    assert "Potential Answer:" in result
    assert "Follow-up:" in result
    assert "Total planned time: 10 minutes" in result


def test_render_target_output_reports_schema_validation_errors() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "study-slides",
            "payload_json": "{\"topic\": \"AI Agents\", \"slides\": [{\"title\": \"Missing fields\"}]}",
        }
    )

    assert "Schema validation failed" in result


def test_render_target_output_accepts_dict_payload_for_study_slides() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "study-slides",
            "payload_json": {
                "topic": "AI Agents",
                "slides": [
                    {
                        "title": "What Matters",
                        "bullets": ["Agents plan work", "Agents use tools"],
                        "speaker_notes": "Keep this high level.",
                    }
                ],
            },
        }
    )

    assert result.startswith("# Presentation: AI Agents")
    assert "## Slide 1: What Matters" in result


def test_render_target_output_normalizes_legacy_study_slides_fields() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "study-slides",
            "payload_json": {
                "slides": [
                    {
                        "title": "Understanding Memory",
                        "content": ["Hierarchy of memory", "Project and user memory files"],
                        "speaker_notes": "Explain where long-lived guidance belongs.",
                        "slide_number": 1,
                    }
                ]
            },
        }
    )

    assert result.startswith("# Presentation:")
    assert "## Slide 1: Understanding Memory" in result
    assert "- Hierarchy of memory" in result
    assert "slide_number" not in result


def test_render_target_output_rejects_missing_required_fields() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "interview",
            "payload_json": """
            {
              "topic": "AI Agents",
              "objective": "Assess practical agent design judgment.",
              "questions": [
                {
                  "question": "How would you ground an agent in local documents?",
                  "timebox_minutes": 10,
                  "follow_up": "What trade-offs would you watch for?"
                }
              ]
            }
            """
        }
    )

    assert "Schema validation failed" in result
    assert "potential_answer" in result


def test_render_target_output_coerces_integer_like_floats() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "interview",
            "payload_json": """
            {
              "topic": "AI Agents",
              "objective": "Assess practical agent design judgment.",
              "questions": [
                {
                  "question": "How would you ground an agent in local documents?",
                  "timebox_minutes": 10.0,
                  "potential_answer": "A strong answer would cover retrieval, source selection, and citation strategy.",
                  "follow_up": "What trade-offs would you watch for?"
                }
              ]
            }
            """
        }
    )

    assert "# Interview Kit: AI Agents" in result
    assert "Timebox: 10 minutes" in result


def test_render_target_output_uses_declarative_render_spec(tmp_path, monkeypatch) -> None:
    from research_agent import targets

    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: demo
title: Demo Target
description: Demo target for declarative rendering
render_template: markdown_blocks
---

## Instructions

Return the final result by calling `render_target_output`.

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

    monkeypatch.setattr(targets, "SKILLS_DIR", tmp_path / "skills")
    targets._load_all_targets.cache_clear()
    try:
        result = render_target_output.invoke(
            {
                "target_id": "demo",
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
    finally:
        targets._load_all_targets.cache_clear()

    assert "# Demo: Agenda" in result
    assert "## Item 1: Intro" in result
    assert "Minutes: 15" in result
    assert "Total: 20" in result


def test_render_target_output_reports_unknown_target() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "does-not-exist",
            "payload_json": "{}",
        }
    )

    assert "Unknown target" in result


def test_render_target_output_renders_golden_dataset_without_metric_fields() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "golden-dataset",
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

    state = {"files": {}, "target": "golden-dataset"}

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


def test_trigger_dataset_evaluation_scores_exported_golden_dataset_csv(tmp_path, monkeypatch) -> None:
    dataset_csv = tmp_path / "starter.csv"
    dataset_csv.write_text(
        "ID,Coverage Area,Question,Answer,Content\n"
        "Q1,Leave,How do I request parental leave?,Review the leave policy first.,Leave section.\n",
        encoding="utf-8",
    )

    def fake_score_dataset_file(input_csv: str, output_csv: str):
        assert input_csv == str(dataset_csv)
        output_path = Path(output_csv)
        output_path.write_text("scored", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "research_agent.skills.golden_dataset.scripts.golden_dataset_metrics.score_dataset_file",
        fake_score_dataset_file,
    )

    result = tools.trigger_dataset_evaluation.invoke({"file_path": str(dataset_csv)})

    assert "Successfully evaluated dataset" in result
    assert str(tmp_path / "starter-with-metrics.csv") in result
    assert (tmp_path / "starter-with-metrics.csv").exists()


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


def test_finalize_golden_dataset_output_rejects_non_golden_target_state() -> None:
    result = finalize_golden_dataset_output.func(
        payload_json='{"items": [{"id": "Q1", "coverage_area": "General", "question": "Q?", "answer": "A"}]}',
        state={"target": "study-slides"},
    )

    assert "only available when the active target is `golden-dataset`" in result


def test_trigger_dataset_evaluation_rejects_non_golden_target_state(tmp_path) -> None:
    dataset_csv = tmp_path / "starter.csv"
    dataset_csv.write_text(
        "ID,Coverage Area,Question,Answer,Content\n"
        "Q1,Leave,How do I request parental leave?,Review the leave policy first.,Leave section.\n",
        encoding="utf-8",
    )

    result = tools.trigger_dataset_evaluation.func(
        file_path=str(dataset_csv),
        state={"target": "study-slides"},
    )

    assert "only available when the active target is `golden-dataset`" in result


def test_frontend_slides_tool_has_expected_name() -> None:
    assert frontend_slides.name == "frontend-slides"


def test_frontend_slides_generates_html_presentation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OUTPUT_FOLDER", str(tmp_path))

    result = frontend_slides.invoke(
        {
            "presentation_markdown": """
# [Slide 1] Title: Future of AI Evaluation

**Headline:** Transforming LLM deployment from guesswork to guaranteed performance.
**Subtitle:** Automated golden datasets for faster launch confidence.
**Contact:** demo@example.com

* Faster launches
* Lower annotation costs

**Callout:** Trusted evaluation without the spreadsheet grind.

# [Slide 2] Title: The Workflow

**Headline:** Four steps from raw docs to scored answers.
**Body:**
1. Extract
2. Generate
3. Draft
4. Evaluate
""",
            "output_filename": "frontend-slides-smoke.html",
            "deck_title": "Frontend Slides Smoke Test",
            "style_preset": "Creative Voltage",
        }
    )

    output_path = tmp_path / "frontend-slides-smoke.html"
    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")

    assert str(output_path) in result
    assert html.count('<section class="slide') == 2
    assert "Future of AI Evaluation" in html
    assert "Four steps from raw docs to scored answers." in html
    assert "height: 100vh;" in html
