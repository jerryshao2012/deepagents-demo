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
    think_tool,
    frontend_slides,
    frontend_slides_export_pdf,
    frontend_slides_deploy,
    frontend_slides_extract_pptx,
    render_skill_output,
    finalize_golden_dataset_output,
    trigger_dataset_evaluation,
    ls,
    glob,
    read_file,
    write_file,
    read_doc_folder,
    tavily_search,
    fetch_webpage_content,
)

__all__ = [
    "think_tool",
    "frontend_slides",
    "frontend_slides_export_pdf",
    "frontend_slides_deploy",
    "frontend_slides_extract_pptx",
    "render_skill_output",
    "finalize_golden_dataset_output",
    "trigger_dataset_evaluation",
    "ls",
    "glob",
    "read_file",
    "write_file",
    "read_doc_folder",
    "tavily_search",
    "fetch_webpage_content",
    "RESEARCHER_INSTRUCTIONS",
    "RESEARCH_WORKFLOW_INSTRUCTIONS",
    "SUBAGENT_DELEGATION_INSTRUCTIONS",
]
