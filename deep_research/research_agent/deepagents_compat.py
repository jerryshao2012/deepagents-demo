"""Compatibility patches for deepagents integration quirks."""

from __future__ import annotations

from typing import Annotated, Any

from langchain.tools import BaseTool, ToolRuntime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from langgraph.types import Command


def _extract_subagent_result_text(message: Any) -> str:
    """Extract human-readable text from a subagent's final message."""
    if message is None:
        return ""

    text_value = getattr(message, "text", None)
    if isinstance(text_value, str) and text_value.strip():
        return text_value

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)

    if isinstance(content, dict):
        text = content.get("text") or content.get("content")
        if text:
            return str(text)

    return str(content) if content is not None else ""


def patch_deepagents_task_tool_result_extraction() -> None:
    """Patch deepagents so task tool results preserve non-.text final content."""
    import deepagents.middleware.subagents as subagents_module

    if getattr(subagents_module, "_deep_research_task_patch_applied", False):
        return

    def _build_task_tool(
            subagents: list[dict[str, Any]],
            task_description: str | None = None,
    ) -> BaseTool:
        subagent_graphs: dict[str, Runnable] = {
            spec["name"]: spec["runnable"] for spec in subagents
        }
        subagent_description_str = "\n".join(
            f"- {spec['name']}: {spec['description']}" for spec in subagents
        )

        if task_description is None:
            description = subagents_module.TASK_TOOL_DESCRIPTION.format(
                available_agents=subagent_description_str
            )
        elif "{available_agents}" in task_description:
            description = task_description.format(
                available_agents=subagent_description_str
            )
        else:
            description = task_description

        def _return_command_with_state_update(result: dict, tool_call_id: str) -> Command:
            if "messages" not in result:
                error_msg = (
                    "CompiledSubAgent must return a state containing a 'messages' key. "
                    "Custom StateGraphs used with CompiledSubAgent should include 'messages' "
                    "in their state schema to communicate results back to the main agent."
                )
                raise ValueError(error_msg)

            state_update = {
                k: v
                for k, v in result.items()
                if k not in subagents_module._EXCLUDED_STATE_KEYS
            }
            message_text = _extract_subagent_result_text(result["messages"][-1]).rstrip()
            return Command(
                update={
                    **state_update,
                    "messages": [ToolMessage(message_text, tool_call_id=tool_call_id)],
                }
            )

        def _build_subagent_context_message(state: dict) -> SystemMessage | None:
            """Build a SystemMessage with task configuration context for the subagent.

            This ensures subagents know about configured resources (doc_folder,
            skill, no_web) so they can call the right tools — even when the
            orchestrator's task description doesn't explicitly mention them.
            """
            parts: list[str] = []

            doc_folder = state.get("doc_folder")
            # Fallback: subagent state schema may not include doc_folder.
            if not doc_folder:
                import os as _os
                doc_folder = _os.environ.get("DOC_FOLDER")
            if doc_folder:
                parts.append(
                    f"A document folder is configured for this research task: '{doc_folder}'.\n"
                    "You MUST use the `read_doc_folder` tool with this path whenever you need "
                    "to access or reference document content. Previously extracted files are "
                    "cached on disk, so repeated calls are fast.\n"
                    "IMPORTANT: After calling `read_doc_folder`, use ONLY the file paths "
                    "returned in the tool output. Do NOT assume filenames from the task "
                    "description are correct — always discover actual files via the tool."
                )

            skill = state.get("skill")
            if skill:
                parts.append(f"The selected skill is `{skill}`.")

            no_web = state.get("no_web")
            if no_web:
                parts.append(
                    "**Web search is DISABLED for this task.** "
                    "Do NOT use tavily_search. Rely on local documents and internal knowledge only."
                )

            if not parts:
                return None

            return SystemMessage(
                content="Task context (injected automatically):\n" + "\n".join(parts)
            )

        def _validate_and_prepare_state(
                subagent_type: str, description: str, runtime: ToolRuntime
        ) -> tuple[Runnable, dict]:
            subagent = subagent_graphs[subagent_type]
            subagent_state = {
                k: v
                for k, v in runtime.state.items()
                if k not in subagents_module._EXCLUDED_STATE_KEYS
            }

            # Build messages: optional context SystemMessage + task HumanMessage
            messages: list = []
            context_msg = _build_subagent_context_message(subagent_state)
            if context_msg:
                messages.append(context_msg)
            messages.append(HumanMessage(content=description))
            subagent_state["messages"] = messages

            return subagent, subagent_state

        def task(
                description: Annotated[
                    str,
                    "A detailed description of the task for the subagent to perform autonomously. Include all necessary context and specify the expected output format.",
                ],
                subagent_type: Annotated[
                    str,
                    "The type of subagent to use. Must be one of the available agent types listed in the tool description.",
                ],
                runtime: ToolRuntime,
        ) -> str | Command:
            if subagent_type not in subagent_graphs:
                allowed_types = ", ".join(f"`{name}`" for name in subagent_graphs)
                return (
                    f"We cannot invoke subagent {subagent_type} because it does not exist, "
                    f"the only allowed types are {allowed_types}"
                )
            if not runtime.tool_call_id:
                raise ValueError("Tool call ID is required for subagent invocation")
            subagent, subagent_state = _validate_and_prepare_state(
                subagent_type, description, runtime
            )
            result = subagent.invoke(subagent_state)
            return _return_command_with_state_update(result, runtime.tool_call_id)

        async def atask(
                description: Annotated[
                    str,
                    "A detailed description of the task for the subagent to perform autonomously. Include all necessary context and specify the expected output format.",
                ],
                subagent_type: Annotated[
                    str,
                    "The type of subagent to use. Must be one of the available agent types listed in the tool description.",
                ],
                runtime: ToolRuntime,
        ) -> str | Command:
            if subagent_type not in subagent_graphs:
                allowed_types = ", ".join(f"`{name}`" for name in subagent_graphs)
                return (
                    f"We cannot invoke subagent {subagent_type} because it does not exist, "
                    f"the only allowed types are {allowed_types}"
                )
            if not runtime.tool_call_id:
                raise ValueError("Tool call ID is required for subagent invocation")
            subagent, subagent_state = _validate_and_prepare_state(
                subagent_type, description, runtime
            )
            result = await subagent.ainvoke(subagent_state)
            return _return_command_with_state_update(result, runtime.tool_call_id)

        return StructuredTool.from_function(
            name="task",
            func=task,
            coroutine=atask,
            description=description,
        )

    subagents_module._build_task_tool = _build_task_tool
    subagents_module._deep_research_task_patch_applied = True
