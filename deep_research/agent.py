"""Research Agent - Standalone script for LangGraph deployment.

This module creates a deep research agent with custom tools and prompts
for conducting web research with strategic thinking and context management.
"""
from datetime import datetime
from typing import Any

from deepagents import create_deep_agent, SubAgent
from dotenv import load_dotenv
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from model_factory import get_configured_model
from research_agent.cli import build_instruction
from research_agent.prompts import (
    RESEARCHER_INSTRUCTIONS,
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.tools import (
    finalize_golden_dataset_output,
    read_doc_folder,
    render_target_output,
    tavily_search,
    think_tool,
    trigger_dataset_evaluation,
)
from utils import get_ssl_verify_config, str2bool

# Load environment variables
load_dotenv()

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits
max_concurrent_research_units = 3
max_researcher_iterations = 3

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")


class ResearchState(AgentState):
    doc_folder: str | None
    no_web: bool | None
    target: str | None


class CLIInstructionMiddleware(AgentMiddleware[ResearchState, Any, Any]):
    def before_agent(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        has_config = any(
            isinstance(m, SystemMessage) and m.content and "Task configurations:" in str(m.content)
            for m in messages
        )
        if has_config:
            return None

        instruction = build_instruction(
            subject="",
            doc_folder=state.get("doc_folder"),
            target=state.get("target"),
            no_web=str2bool(state.get("no_web"), False)
        )
        instruction = instruction.replace("Research the following subject: ", "").strip()

        if instruction:
            return {"messages": [SystemMessage(content="Task configurations:\n" + instruction)]}
        return None


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

# Create research subagent
research_sub_agent: SubAgent = {
    "name": "research-agent",
    "description": "Delegate research to the sub-agent researcher. Only give this researcher one topic at a time.",
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
    "tools": [
        tavily_search,
        think_tool,
        read_doc_folder,
        render_target_output,
        finalize_golden_dataset_output,
        trigger_dataset_evaluation,
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
        render_target_output,
        finalize_golden_dataset_output,
        trigger_dataset_evaluation,
    ],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
    middleware=[CLIInstructionMiddleware()],
)
