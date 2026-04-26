import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from deepagents import create_deep_agent, SubAgent
from deepagents.backends.utils import create_file_data
from dotenv import load_dotenv
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from logger_utils import setup_logger
from model_factory import get_configured_model
from research_agent import (
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.prompts import RESEARCHER_DESCRIPTION
from research_agent.tools import (
    normalize_path_for_filesystem_tools,
    think_tool,
    render_skill_output,
    finalize_golden_dataset_output,
    ls,
    glob,
    read_file,
    read_doc_folder,
    write_file,
    tavily_search,
    fetch_webpage_content,
)
from research_agent.utils.cli import (
    build_instruction,
)
from research_agent.utils.eval_tracking import log_server_metrics
from research_agent.utils.skill_registry import get_skill_registry
from utils import get_ssl_verify_config, str2bool

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits - configurable via environment variables
MAX_CONCURRENT_RESEARCH_UNITS = int(os.environ.get("MAX_CONCURRENT_RESEARCH_UNITS", "3"))
MAX_RESEARCHER_ITERATIONS = int(os.environ.get("MAX_RESEARCHER_ITERATIONS", "3"))

# Evaluation tracking - configurable via environment variables
ENABLE_EVAL_TRACKING = str2bool(os.environ.get("ENABLE_EVAL_TRACKING"), False)
EVAL_HISTORY_FILE = os.environ.get("EVAL_HISTORY_FILE", "./output/eval_history/server_runs.jsonl")

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")

# Initialize dynamic skill registry (use singleton to avoid duplicate initialization)
skill_registry = get_skill_registry()


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
        logger.error(f"Warning: Skills directory not found: {skills_path}")
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
            logger.error(f"Warning: Failed to load keywords from {skill_file}: {e}")
            continue

    return skill_keywords


# Load skill keywords from SKILL.md files
SKILL_KEYWORDS = load_skill_keywords()


class ResearchState(AgentState):
    """Runtime state for the research agent."""
    doc_folder: str | None
    skill: str | None
    no_web: bool | None
    chat_start_time: float | None
    chat_elapsed_seconds: float | None
    files: dict | None
    _eval_logged: bool


class ResearchStateMiddleware(AgentMiddleware):
    """Middleware to configure state variables like DOC_FOLDER before the agent runs."""

    # Ensure middleware state update are validated against the standard state schema.
    state_schema = ResearchState

    @staticmethod
    def _get_current_user_message(messages: list) -> str | None:
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                return str(m.get("content", ""))
            if hasattr(m, "type") and getattr(m, "type", None) == "human":
                return str(getattr(m, "content", ""))
        return None

    @staticmethod
    def _seed_research_request_file(user_message: str | None, state: ResearchState) -> dict[str, Any]:
        """Make the current request available to subagents before the model decides its next step."""
        if not user_message:
            return {}

        existing_files = state.get("files", {})
        existing_request = existing_files.get("/research_request.md")
        if isinstance(existing_request, dict):
            existing_content = "\n".join(existing_request.get("content", []))
            if existing_content == user_message:
                return {}

        return {
            "files": {
                "/research_request.md": create_file_data(user_message),
            }
        }

    def before_agent(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        current_user_message = self._get_current_user_message(messages)

        # Check if system instructions already exist
        updates: dict[str, Any] = self._seed_research_request_file(current_user_message, state)
        has_config = any(
            isinstance(m, SystemMessage) and m.content and "Task configurations:" in str(m.content)
            for m in messages
        )
        if has_config:
            return updates if updates else None

        # Step 1: Extract doc_folder and skill from user message if not already set
        extracted_updates = self._extract_parameters_from_user_input(state, messages)
        updates.update(extracted_updates)

        # Step 2: Configure OUTPUT_FOLDER based on extracted doc_folder
        if updates.get("doc_folder") or (state.get("doc_folder") and not extracted_updates):
            doc_folder = updates.get("doc_folder") or state.get("doc_folder")
            self._configure_output_folder(doc_folder)
        else:
            self._configure_output_folder(None)

        # Step 3: Build instruction based on full state (including extracted parameters)
        merged_state: ResearchState = {**state, **updates}  # type: ignore[assignment]
        instruction = self._build_system_instruction(merged_state)

        result = updates if updates else {}
        if instruction:
            result["messages"] = [SystemMessage(content=f"Task configurations: \n{instruction}")]

        return result if result else None

    def before_model(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        """Capture chat_start_time before model calls, only initializing once per chat."""
        # Initialize once; do not reset on subsequent model turns.
        if isinstance(state.get("chat_start_time"), (int, float)):
            return None

        chat_start_time = time.time()
        return {
            "chat_start_time": chat_start_time,
            "chat_elapsed_seconds": None,
            "_eval_logged": False,
        }

    def after_model(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        """Calculate chat_elapsed_seconds after each model response and optionally track eval metrics."""
        chat_start_time = state.get("chat_start_time")
        updates = {}

        if isinstance(chat_start_time, (int, float)):
            chat_elapsed_seconds = time.time() - chat_start_time
            updates["chat_elapsed_seconds"] = chat_elapsed_seconds

        # Optional: Log eval metrics on completion (when graph is done)
        # This checks if we're at the end of execution by looking for final artifacts
        if ENABLE_EVAL_TRACKING and state.get("files"):
            files = state.get("files", {})
            if not isinstance(files, dict):
                return updates if updates else None

            has_final_output = "/final_report.md" in files

            # Check if already logged (use .get() with default False since TypedDict doesn't support defaults)
            if has_final_output and not state.get("_eval_logged", False):
                # Mark as logged to avoid duplicate logging
                updates["_eval_logged"] = True

                # Calculate runtime
                runtime_seconds = 0.0
                if isinstance(chat_start_time, (int, float)):
                    runtime_seconds = time.time() - chat_start_time

                # Extract data from state
                messages = state.get("messages", [])
                doc_folder = state.get("doc_folder") or os.environ.get("DOC_FOLDER", "unknown")
                skill = state.get("skill", "unknown")
                no_web = state.get("no_web", False)
                model_name = os.environ.get("MODEL_NAME", "unknown")

                # Get user message as subject (for reference only, not for comparison)
                user_message = None
                for m in messages:
                    if isinstance(m, dict) and m.get("role") == "user":
                        user_message = m.get("content", "")
                        break
                    elif hasattr(m, "type") and getattr(m, "type", None) == "human":
                        user_message = getattr(m, "content", "")
                        break
                subject = user_message

                # Build context
                context = {
                    "subject": subject,
                    "skill": skill,
                    "doc_folder": doc_folder,
                    "no_web": no_web,
                }

                # Call centralized logging function
                try:
                    summary = log_server_metrics(
                        messages=messages,
                        files=files,
                        runtime_seconds=runtime_seconds,
                        model_name=model_name,
                        context=context,
                        history_file=EVAL_HISTORY_FILE,
                    )

                    # Log summary
                    logger.info(
                        f"✅ Metrics logged: {summary['runtime_seconds']}s | "
                        f"{summary['tool_calls']} tools ({summary['success_rate']:.0%} success) | "
                        f"{summary['total_tokens']} tokens | "
                        f"param quality: {summary['param_quality']:.2f} | "
                        f"{summary['corrections']} corrections"
                    )
                except Exception as e:
                    logger.error(f"⚠️  Eval tracking error: {e}")

        return updates if updates else None

    def _extract_parameters_from_user_input(self, state: ResearchState, messages: list) -> dict[str, Any]:
        """Extract doc_folder, skill, and no_web from user message patterns."""
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

        # Extract skill if not already set
        if not state.get("skill"):
            updates["skill"] = self._extract_skill(user_message)

        # Extract no_web if not already set
        if state.get("no_web") is None:
            no_web_value = self._extract_no_web(user_message)
            if no_web_value is not None:
                updates["no_web"] = no_web_value

        # Remove None values from updates
        return {k: v for k, v in updates.items() if v is not None}

    @staticmethod
    def _configure_output_folder(doc_folder: str | None) -> None:
        """Configure OUTPUT_FOLDER and DOC_FOLDER environment variables.

        DOC_FOLDER is persisted as an env var so that subagent state schemas
        (which may not include ``doc_folder``) can still access it as a
        fallback inside ``read_doc_folder``.
        """
        reports_output_folder = os.environ.get("REPORTS_OUTPUT_FOLDER", "./output")
        if not doc_folder:
            output_folder = reports_output_folder
        else:
            output_folder = str(Path(reports_output_folder) / Path(doc_folder).name)

        # Normalize path for deepagents filesystem tools compatibility (cross-platform)
        normalized_path = normalize_path_for_filesystem_tools(output_folder)
        os.environ["OUTPUT_FOLDER"] = normalized_path

        # Persist doc_folder so read_doc_folder can fall back to it inside
        # subagents whose state schema doesn't carry the key.
        if doc_folder:
            os.environ["DOC_FOLDER"] = doc_folder
        else:
            os.environ.pop("DOC_FOLDER", None)

    @staticmethod
    def _extract_doc_folder(user_message: str) -> str | None:
        """Extract doc_folder from user message patterns and verify it exists."""
        potential_path: str | None = None

        # Look for --doc-folder pattern
        doc_match = re.search(r"--doc-folder\s+['\"]?([^\s'\"]+)['\"]?", user_message)
        if doc_match:
            # Normalize Windows backslashes to forward slashes
            potential_path = doc_match.group(1).replace('\\', '/')

        if not potential_path:
            # Look for path patterns like ./docs/policy/ or .\docs\policy\ or quoted paths
            path_match = re.search(r"['\"](\.[/\\][^'\"]+)['\"]", user_message)
            if path_match:
                p = path_match.group(1).replace('\\', '/')
                if "doc" in p.lower() or "policy" in p.lower() or "folder" in p.lower():
                    potential_path = p

        if not potential_path:
            # Look for unquoted paths that contain common document folder names
            # Matches ./path/to/dir, /path/to/dir, or path/to/dir
            unquoted_match = re.search(r"((?:\.?/)?[\\w/.-]+(?:[/\\][\\w/.-]+)+)", user_message)
            if unquoted_match:
                p = unquoted_match.group(1).replace('\\', '/')
                if any(keyword in p.lower() for keyword in ["doc", "policy", "data", "input", "file"]):
                    potential_path = p

        if not potential_path:
            return None

        # Verify the path exists; if not, check if it's inside 'deep_research'
        path = Path(potential_path)
        if not path.exists():
            # Try to prefix with deep_research if not already
            if not potential_path.startswith("./deep_research/") and not potential_path.startswith("deep_research/"):
                deep_path = Path("deep_research") / potential_path.lstrip("./")
                if deep_path.exists():
                    return str(deep_path)

        return potential_path

    @staticmethod
    def _extract_skill(user_message: str) -> str | None:
        """Extract skill from user message patterns using dynamic skill registry."""
        # Look for --skill pattern
        skill_match = re.search(r"--skill\s+([^\s]+)", user_message)
        if skill_match:
            return skill_match.group(1)

        # Use skill registry to find matching skills by keyword
        message_lower = user_message.lower()
        matches = skill_registry.find_skills_by_keyword(message_lower)
        if matches:
            # Return the first match (most relevant based on keyword priority)
            return matches[0].skill_id

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
            skill=state.get("skill"),
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
    max_concurrent_research_units=MAX_CONCURRENT_RESEARCH_UNITS,
    max_researcher_iterations=MAX_RESEARCHER_ITERATIONS)
)

# Create research subagent
# The sub-agent is intentionally web-only to keep delegation focused and avoid
# filesystem/state write confusion inside isolated sub-agent contexts.
research_sub_agent: SubAgent = {
    "name": "research-agent",
    "description": RESEARCHER_DESCRIPTION,
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(
        date=current_date,
        skill_catalog=get_skill_registry().format_skill_catalog(),
        skill_quality_guidelines=get_skill_registry().format_skill_quality_guidelines(),
    ),
    "tools": [
        tavily_search,
        fetch_webpage_content,
        think_tool,
    ],
}

model = get_configured_model()

# Recursion limit - configurable via environment variable (applied at graph compile time)
RECURSION_LIMIT = int(os.environ.get("GRAPH_RECURSION_LIMIT", "200"))

# Create the agent
# Orchestrator owns document/filesystem tools and structured-output finalization.
# Web discovery can still be delegated to `research-agent` via task().
agent = create_deep_agent(
    model=model,
    tools=[
        think_tool,
        read_file,
        write_file,
        ls,
        glob,
        read_doc_folder,
        render_skill_output,
        finalize_golden_dataset_output,
    ],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
    middleware=[ResearchStateMiddleware()],
).with_config(RunnableConfig(recursion_limit=RECURSION_LIMIT))
