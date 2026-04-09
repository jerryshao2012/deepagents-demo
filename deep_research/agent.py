"""Research Agent - Standalone script for LangGraph deployment.

This module creates a deep research agent with custom tools and prompts
for conducting web research with strategic thinking and context management.
"""
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from deepagents import create_deep_agent, SubAgent
from dotenv import load_dotenv
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from model_factory import get_configured_model
from research_agent.cli import build_instruction
from research_agent.deepagents_compat import patch_deepagents_task_tool_result_extraction
from research_agent.prompts import (
    RESEARCHER_INSTRUCTIONS,
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.tools import (
    finalize_golden_dataset_output,
    read_doc_folder,
    read_file,
    ls,
    glob,
    render_target_output,
    tavily_search,
    think_tool,
    trigger_dataset_evaluation,
    _normalize_path_for_filesystem_tools,
    REPORTS_OUTPUT_FOLDER,
)
from utils import get_ssl_verify_config, str2bool

# Load environment variables
load_dotenv()

# Ensure task() returns the subagent's final content even when it is not stored in `.text`.
patch_deepagents_task_tool_result_extraction()

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits
max_concurrent_research_units = 3
max_researcher_iterations = 3

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")


def load_skill_keywords(skills_dir: str | None = None) -> dict[str, list[str]]:
    """Load skill keywords from SKILL.md frontmatter.
    
    Scans all SKILL.md files in the skills directory and extracts keywords
    from the YAML frontmatter. This externalizes keyword configuration from
    code to skill definition files.
    
    Args:
        skills_dir: Path to skills directory. Defaults to research_agent/skills/
        
    Returns:
        Dictionary mapping skill names to their keyword lists
    """
    if skills_dir is None:
        # Default to the skills directory relative to this file
        skills_path = Path(__file__).parent / "research_agent" / "skills"
    else:
        skills_path = Path(skills_dir)

    if not skills_path.exists():
        print(f"Warning: Skills directory not found: {skills_path}")
        return {}

    skill_keywords = {}

    # Scan all subdirectories for SKILL.md files
    for skill_dir in skills_path.iterdir():
        if not skill_dir.is_dir():
            continue

        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        try:
            content = skill_file.read_text(encoding="utf-8")

            # Extract YAML frontmatter (between --- markers)
            if not content.startswith("---"):
                continue

            # Find the end of frontmatter
            end_marker = content.find("\n---", 3)
            if end_marker == -1:
                continue

            frontmatter_text = content[3:end_marker]
            frontmatter = yaml.safe_load(frontmatter_text)

            # Extract skill name and keywords
            skill_name = frontmatter.get("name")
            keywords = frontmatter.get("keywords", [])

            if skill_name and keywords:
                skill_keywords[skill_name] = keywords

        except Exception as e:
            print(f"Warning: Failed to load keywords from {skill_file}: {e}")
            continue

    return skill_keywords


# Load skill keywords from SKILL.md files
SKILL_KEYWORDS = load_skill_keywords()


class ResearchState(AgentState):
    doc_folder: str | None
    no_web: bool | None
    target: str | None
    agent_start_time: float | None


class ResearchStateMiddleware(AgentMiddleware):
    """
    Unified middleware that handles both parsing user input and building system instructions.
    1. Parses natural language user input to extract doc_folder, target, and no_web
    2. Builds system instructions based on the full ResearchState
    """
    state_schema = ResearchState

    def before_agent(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        import time
        messages = state.get("messages", [])

        # Capture agent start time if not already set
        updates: dict[str, Any] = {}
        if state.get("agent_start_time") is None:
            updates["agent_start_time"] = time.time()

        # Check if system instructions already exist
        has_config = any(
            isinstance(m, SystemMessage) and m.content and "Task configurations:" in str(m.content)
            for m in messages
        )
        if has_config:
            return updates if updates else None

        # Step 1: Extract doc_folder and target from user message if not already set
        extracted_updates = self._extract_parameters_from_user_input(state, messages)
        updates.update(extracted_updates)

        # Step 2: Configure OUTPUT_FOLDER based on extracted doc_folder
        if updates.get("doc_folder") or (state.get("doc_folder") and not extracted_updates):
            doc_folder = updates.get("doc_folder") or state.get("doc_folder")
            self._configure_output_folder(doc_folder)

        # Step 3: Build instruction based on full state (including extracted parameters)
        merged_state: ResearchState = {**state, **updates}  # type: ignore[assignment]
        instruction = self._build_system_instruction(merged_state)

        result = updates if updates else {}
        if instruction:
            result["messages"] = [SystemMessage(content=f"Task configurations: \n{instruction}")]

        return result if result else None

    def _extract_parameters_from_user_input(self, state: ResearchState, messages: list) -> dict[str, Any]:
        """Extract doc_folder, target, and no_web from user message patterns."""
        user_message = None
        for m in messages:
            # Handle dictionary messages
            if isinstance(m, dict):
                if m.get("role") == "user":
                    user_message = m.get("content")
                    break
            # Handle LangChain message objects (not SystemMessage)
            elif hasattr(m, "content") and not isinstance(m, SystemMessage):
                # Check if it's a HumanMessage or similar user message type
                if hasattr(m, "type") and m.type == "human":
                    user_message = m.content
                    break
                # Fallback: if it has content and isn't a SystemMessage, treat as user message
                elif not hasattr(m, "type"):
                    user_message = m.content
                    break

        if not user_message:
            return {}

        user_message = str(user_message)
        updates = {}

        # Extract doc_folder if not already set
        if not state.get("doc_folder"):
            updates["doc_folder"] = self._extract_doc_folder(user_message)

        # Extract target if not already set
        if not state.get("target"):
            updates["target"] = self._extract_target(user_message)

        # Extract no_web if not already set
        if state.get("no_web") is None:
            no_web_value = self._extract_no_web(user_message)
            if no_web_value is not None:
                updates["no_web"] = no_web_value

        # Remove None values from updates
        return {k: v for k, v in updates.items() if v is not None}

    @staticmethod
    def _configure_output_folder(doc_folder: str | None) -> None:
        """Configure OUTPUT_FOLDER environment variable based on doc_folder."""
        if not doc_folder:
            output_folder = REPORTS_OUTPUT_FOLDER
        else:
            output_folder = str(Path(REPORTS_OUTPUT_FOLDER) / Path(doc_folder).name)

        # Normalize path for deepagents filesystem tools compatibility (cross-platform)
        normalized_path = _normalize_path_for_filesystem_tools(output_folder)
        os.environ["OUTPUT_FOLDER"] = normalized_path

    @staticmethod
    def _extract_doc_folder(user_message: str) -> str | None:
        """Extract doc_folder from user message patterns."""
        # Look for --doc-folder pattern
        doc_match = re.search(r"--doc-folder\s+['\"]?([^\s'\"]+)['\"]?", user_message)
        if doc_match:
            # Normalize Windows backslashes to forward slashes
            return doc_match.group(1).replace('\\', '/')

        # Look for path patterns like ./docs/policy/ or .\docs\policy\ or quoted paths
        path_match = re.search(r"['\"](\.[/\\][^'\"]+)['\"]", user_message)
        if path_match:
            potential_path = path_match.group(1)
            # Normalize Windows backslashes to forward slashes
            potential_path = potential_path.replace('\\', '/')
            if "doc" in potential_path.lower() or "policy" in potential_path.lower() or "folder" in potential_path.lower():
                return potential_path

        # Look for unquoted paths that contain common document folder names
        unquoted_match = re.search(r"(\.[/\\][\w/\\.]+)", user_message)
        if unquoted_match:
            potential_path = unquoted_match.group(1)
            # Normalize Windows backslashes to forward slashes
            potential_path = potential_path.replace('\\', '/')
            if any(keyword in potential_path.lower() for keyword in ["doc", "policy", "data", "input", "file"]):
                return potential_path

        return None

    @staticmethod
    def _extract_target(user_message: str) -> str | None:
        """Extract target from user message patterns."""
        # Look for --target pattern
        target_match = re.search(r"--target\s+([^\s]+)", user_message)
        if target_match:
            return target_match.group(1)

        # Look for skill names mentioned in the message using global SKILL_KEYWORDS
        message_lower = user_message.lower()
        for skill_name, keywords in SKILL_KEYWORDS.items():
            for keyword in keywords:
                if re.search(keyword, message_lower):
                    return skill_name

        return None

    @staticmethod
    def _extract_no_web(user_message: str) -> bool | None:
        """Extract no_web flag from user message patterns."""
        message_lower = user_message.lower()

        # Patterns that indicate no_web should be True
        disable_patterns = [
            r"without\s+web",
            r"no\s+web",
            r"disable\s+web",
            r"offline",
            r"no\s+internet",
            r"no\s+search",
            r"disable\s+search",
            r"--no-web",
            r"-n(?:\s|$)",
        ]

        for pattern in disable_patterns:
            if re.search(pattern, message_lower):
                return True

        # Patterns that indicate no_web should be False (explicit enable)
        enable_patterns = [
            r"with\s+web",
            r"with\s+search",
            r"enable\s+search",
            r"search\s+the\s+web",
        ]

        for pattern in enable_patterns:
            if re.search(pattern, message_lower):
                return False

        return None

    @staticmethod
    def _build_system_instruction(state: ResearchState) -> str:
        """Build system instruction from ResearchState parameters."""
        instruction = build_instruction(
            subject="",
            doc_folder=state.get("doc_folder"),
            target=state.get("target"),
            no_web=str2bool(state.get("no_web"), False)
        )
        instruction = instruction.replace("Research the following subject: ", "").strip()

        return instruction


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
        read_file,
        ls,
        glob,
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
        read_file,
        ls,
        glob,
        read_doc_folder,
        render_target_output,
        finalize_golden_dataset_output,
        trigger_dataset_evaluation,
    ],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
    middleware=[ResearchStateMiddleware()],
)
