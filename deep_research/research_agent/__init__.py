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
    frontend_slides,
    frontend_slides_export_pdf,
    frontend_slides_deploy,
    frontend_slides_extract_pptx,
    finalize_golden_dataset_output,
    think_tool,
    trigger_dataset_evaluation,
    read_doc_folder,
)
from research_agent.utils.knowledge_filesystem import (
    ls,
    glob,
    read_file,
)
from research_agent.utils.result_rendering import (
    render_target_output,
)
from research_agent.utils.web_search import (
    tavily_search,
    fetch_webpage_content,
)

__all__ = [
    "tavily_search",
    "fetch_webpage_content",
    "think_tool",
    "ls",
    "glob",
    "read_file",
    "read_doc_folder",
    "frontend_slides",
    "frontend_slides_export_pdf",
    "frontend_slides_deploy",
    "frontend_slides_extract_pptx",
    "finalize_golden_dataset_output",
    "trigger_dataset_evaluation",
    "render_target_output",
    "RESEARCHER_INSTRUCTIONS",
    "RESEARCH_WORKFLOW_INSTRUCTIONS",
    "SUBAGENT_DELEGATION_INSTRUCTIONS",
]
