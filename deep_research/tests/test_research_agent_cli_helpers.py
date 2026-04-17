import os
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from research_agent_cli import (
    configure_output_folder,
    derive_output_folder,
    select_output_content,
    should_retry_with_invoke,
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
                name="render_target_output",
            ),
            AIMessage(
                content="The research task has been delegated and I am awaiting the results."
            ),
        ]
    }

    assert select_output_content(result, "study-slides").startswith("# Presentation:")


def test_select_output_content_ignores_failed_render_and_uses_task_output_for_structured_targets() -> None:
    result = {
        "messages": [
            ToolMessage(
                content="Invalid JSON payload: Expecting ',' delimiter",
                tool_call_id="tool-1",
                name="render_target_output",
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


def test_should_retry_with_invoke_when_result_is_only_delegation_placeholder() -> None:
    result = {
        "messages": [
            AIMessage(
                content=(
                    'I have delegated the research on "Claude Code Memory Management" '
                    "to a specialized research agent. Once the agent returns its findings, "
                    "I will synthesize the information into a quick-learning presentation format."
                )
            )
        ]
    }

    assert should_retry_with_invoke(result, "study-slides") is True


def test_should_not_retry_with_invoke_when_structured_output_is_present() -> None:
    result = {
        "messages": [
            ToolMessage(
                content="# Presentation: Claude Code Memory\n\n## Slide 1: Basics\n",
                tool_call_id="tool-1",
                name="render_target_output",
            )
        ]
    }

    assert should_retry_with_invoke(result, "study-slides") is False


def test_should_retry_with_invoke_when_todos_are_not_completed() -> None:
    result = {
        "todos": [
            {"content": "Save the request to /research_request.md", "status": "in_progress"},
            {"content": "Research an overview of LLM wiki", "status": "pending"},
        ],
        "messages": [
            ToolMessage(
                content="Updated todo list",
                tool_call_id="tool-1",
                name="write_todos",
            )
        ],
    }
    assert should_retry_with_invoke(result, None) is True
