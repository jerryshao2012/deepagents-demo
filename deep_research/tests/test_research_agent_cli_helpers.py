import os
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from research_agent_cli import (
    configure_output_folder,
    derive_output_folder,
    select_output_content,
)


def test_derive_output_folder_uses_final_doc_folder_segment() -> None:
    assert derive_output_folder("./doc/policy") == Path("output") / "policy"
    assert derive_output_folder("./docs/policy") == Path("output") / "policy"


def test_configure_output_folder_overwrites_stale_env_value(monkeypatch) -> None:
    monkeypatch.setenv("OUTPUT_FOLDER", "output/docs/old")

    output_folder = configure_output_folder("./doc/policy")

    assert output_folder == Path("output") / "policy"
    assert os.environ["OUTPUT_FOLDER"] == "output/policy"


def test_select_output_content_prefers_rendered_structured_output_over_last_ai_message() -> None:
    result = {
        "messages": [
            ToolMessage(
                content="# Presentation: Claude Code Memory\n\n## Slide 1: Basics\n",
                tool_call_id="tool-1",
                name="render_skill_output",
            ),
            AIMessage(
                content="The research task has been delegated and I am awaiting the results."
            ),
        ]
    }

    assert select_output_content(result, "study-slides").startswith("# Presentation:")


def test_select_output_content_ignores_failed_render_and_uses_task_output_for_structured_skills() -> None:
    result = {
        "messages": [
            ToolMessage(
                content="Invalid JSON payload: Expecting ',' delimiter",
                tool_call_id="tool-1",
                name="render_skill_output",
            ),
            ToolMessage(
                content="# Presentation: Claude Code Memory\n\n## Slide 1: Basics\n",
                tool_call_id="tool-2",
                name="task",
            ),
            AIMessage(content="I am awaiting the results."),
        ]
    }

    assert select_output_content(result, "study-slides").startswith("# Presentation:")
