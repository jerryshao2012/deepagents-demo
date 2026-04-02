"""Research Agent - Standalone script for LangGraph deployment.

This module creates a deep research agent with custom tools and prompts
for conducting web research with strategic thinking and context management.
"""
from datetime import datetime

from deepagents import create_deep_agent, SubAgent
from dotenv import load_dotenv

from model_factory import get_configured_model
from research_agent.prompts import (
    RESEARCHER_INSTRUCTIONS,
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.tools import (
    read_doc_folder,
    render_target_output,
    tavily_search,
    think_tool
)
from utils import get_ssl_verify_config

# Load environment variables
load_dotenv()

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits
max_concurrent_research_units = 3
max_researcher_iterations = 3

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")

# Combine orchestrator instructions (RESEARCHER_INSTRUCTIONS only for sub-agents)
INSTRUCTIONS = (
        RESEARCH_WORKFLOW_INSTRUCTIONS
        + "\n\n"
        + "=" * 80
        + "\n\n"
        + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
    max_concurrent_research_units=max_concurrent_research_units,
    max_researcher_iterations=max_researcher_iterations)
)

# Create research sub-agent
research_sub_agent: SubAgent = {
    "name": "research-agent",
    "description": "Delegate research to the sub-agent researcher. Only give this researcher one topic at a time.",
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
    "tools": [
        tavily_search,
        think_tool,
        read_doc_folder,
        render_target_output
    ],
}

model = get_configured_model()

# Create the agent
agent = create_deep_agent(
    model=model,
    tools=[
        tavily_search,
        think_tool,
        read_doc_folder,
        render_target_output
    ],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
)
