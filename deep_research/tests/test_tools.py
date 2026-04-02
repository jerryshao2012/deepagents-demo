from pathlib import Path

from research_agent import tools
from research_agent.tools import read_doc_folder, render_target_output


def test_render_target_output_renders_slides_from_definition() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "slides",
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
            "target_id": "slides",
            "payload_json": "{\"topic\": \"AI Agents\", \"slides\": [{\"title\": \"Missing fields\"}]}",
        }
    )

    assert "Schema validation failed" in result


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
            "target_id": "golden_dataset",
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
                  "draft_llm_response": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
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


def test_render_target_output_exports_golden_dataset_content_to_csv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "REPORTS_OUTPUT_FOLDER", str(tmp_path))

    result = render_target_output.invoke(
        {
            "target_id": "golden_dataset",
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
                  "draft_llm_response": "You would typically start by reviewing the leave policy and then submitting the required request through HR.",
                  "content": "The handbook explains eligibility, notice periods, and HR approval steps."
                }
              ]
            }
            """,
        }
    )

    csv_path = tmp_path / "hr_policy_starter.csv"
    assert csv_path.exists()
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Content" in csv_text
    assert "eligibility, notice periods, and HR approval steps" in csv_text
    assert "Context" not in csv_text


def test_read_doc_folder_reads_text_and_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "summary.md").write_text("# heading", encoding="utf-8")

    result = read_doc_folder.invoke({"folder_path": str(tmp_path)})

    assert "--- Content of notes.txt ---" in result
    assert "alpha" in result
    assert "--- Content of summary.md ---" in result
    assert "# heading" in result


def test_read_doc_folder_reports_unsupported_and_empty_cases(tmp_path: Path) -> None:
    (tmp_path / "image.png").write_bytes(b"png")

    result = read_doc_folder.invoke({"folder_path": str(tmp_path)})

    assert "No supported document files found" in result
