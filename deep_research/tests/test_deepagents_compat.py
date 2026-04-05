from types import SimpleNamespace

from langchain_core.runnables import RunnableLambda

from research_agent.deepagents_compat import (
    _extract_subagent_result_text,
    patch_deepagents_task_tool_result_extraction,
)


def test_extract_subagent_result_text_falls_back_to_content() -> None:
    message = SimpleNamespace(
        text="",
        content=[{"type": "text", "text": "Slide-ready findings"}],
    )

    assert _extract_subagent_result_text(message) == "Slide-ready findings"


def test_patched_task_tool_preserves_subagent_content() -> None:
    import deepagents.middleware.subagents as subagents_module

    patch_deepagents_task_tool_result_extraction()

    task_tool = subagents_module._build_task_tool(
        [
            {
                "name": "research-agent",
                "description": "Research agent",
                "runnable": RunnableLambda(
                    lambda _state: {
                        "messages": [
                            SimpleNamespace(
                                text="",
                                content=[{"type": "text", "text": "Rendered study slides"}],
                            )
                        ]
                    }
                ),
            }
        ]
    )

    result = task_tool.func(
        description="Research and return slides",
        subagent_type="research-agent",
        runtime=SimpleNamespace(tool_call_id="call-123", state={"messages": []}),
    )

    tool_message = result.update["messages"][0]
    assert tool_message.content == "Rendered study slides"
