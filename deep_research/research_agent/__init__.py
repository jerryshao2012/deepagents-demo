"""Deep Research Agent Example.

This module demonstrates building a research agent using the deepagents package
with custom tools for web search and strategic thinking.
"""

from research_agent.prompts import (
    RESEARCHER_INSTRUCTIONS,
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.tools import (
    finalize_golden_dataset_output,
    frontend_slides,
    read_doc_folder,
    render_target_output,
    tavily_search,
    think_tool,
    trigger_dataset_evaluation,
)

__all__ = [
    "tavily_search",
    "think_tool",
    "read_doc_folder",
    "frontend_slides",
    "render_target_output",
    "finalize_golden_dataset_output",
    "trigger_dataset_evaluation",
    "RESEARCHER_INSTRUCTIONS",
    "RESEARCH_WORKFLOW_INSTRUCTIONS",
    "SUBAGENT_DELEGATION_INSTRUCTIONS",
]
