from pathlib import Path

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
            """,
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
                  "follow_up": "What trade-offs would you watch for?"
                }
              ]
            }
            """,
        }
    )

    assert "# Interview Kit: AI Agents" in result
    assert "45-minute interview objective" in result
    assert "Timebox: 10 minutes" in result
    assert "Follow-up:" in result


def test_render_target_output_reports_schema_validation_errors() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "slides",
            "payload_json": "{\"topic\": \"AI Agents\", \"slides\": [{\"title\": \"Missing fields\"}]}",
        }
    )

    assert "Schema validation failed" in result


def test_render_target_output_reports_unknown_target() -> None:
    result = render_target_output.invoke(
        {
            "target_id": "does-not-exist",
            "payload_json": "{}",
        }
    )

    assert "Unknown target" in result


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
