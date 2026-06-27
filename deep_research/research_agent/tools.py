"""Tools for the research agent."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from deepagents.backends.utils import create_file_data
from dotenv import load_dotenv
from langchain_core.tools import InjectedToolArg
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from logger_utils import setup_logger
from research_agent.skills.golden_dataset.pipeline import (
    export_golden_dataset_csv,
    evaluate_and_report_golden_dataset,
)
from research_agent.utils.json_utils import robust_json_loads
from research_agent.utils.knowledge_filesystem import (
    normalize_path_for_filesystem_tools,
    ls_impl,
    glob_impl,
    read_file_impl,
    read_doc_folder_impl,
    write_file_impl,
    write_content_to_output_folder,
    send_files_to_state,
)
from research_agent.utils.result_rendering import render_skill_output_impl
from research_agent.utils.skill_registry import get_skill_registry
from research_agent.utils.web_search import (
    fetch_webpage_content_impl,
    tavily_search_impl
)

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)


# --- Web Search Tools ---

@tool(parse_docstring=True)
def fetch_webpage_content(
        url: str,
        state: Annotated[dict, InjectedState],
        timeout: float = 10.0
) -> str:
    """Fetch and convert webpage content to markdown.

    Use this tool to retrieve the full content of a specific webpage URL and convert it to readable markdown format.
    This is useful when you have a specific URL and need to extract its content for analysis or summarization.

    Args:
        url: The URL of the webpage to fetch.
        timeout: Request timeout in seconds (default: 10.0).
        state: LangGraph state containing no_web flag (injected automatically).

    Returns:
        The webpage content converted to markdown format, or an error message if the fetch fails.
    """
    logger.info(f"Fetching webpage content from URL: {url} (timeout: {timeout}s)")

    result = fetch_webpage_content_impl(url, timeout, state)
    logger.info(f"Successfully fetched webpage content from {url}")
    return result


@tool(parse_docstring=True)
def tavily_search(
        query: str,
        state: Annotated[dict, InjectedState],
        max_results: Annotated[int, InjectedToolArg] = 1,
        topic: Annotated[Literal["general", "news", "finance"], InjectedToolArg] = "general",
) -> str:
    """Search the web for information on a given query.

    Uses Tavily to discover relevant URLs, then fetches and returns full webpage content as markdown.

    Args:
        query: Search query to execute
        max_results: Maximum number of results to return (default: 1)
        topic: Topic filter - 'general', 'news', or 'finance' (default: 'general')
        state: LangGraph state

    Returns:
        Formatted search results with full webpage content
    """
    logger.info(f"Executing Tavily search - Query: '{query}', Max Results: {max_results}, Topic: {topic}")

    result = tavily_search_impl(query, max_results, topic, state)
    logger.info(f"Tavily search completed successfully for query: '{query}'")
    return result


# --- Filesystem Tools ---

@tool(parse_docstring=True)
def ls(
        path: str,
        state: Annotated[dict, InjectedState]
) -> str:
    """List files in a directory with fallback support.

    Tries to list from the virtual filesystem in state first (DeepAgents backend),
    then falls back to the local filesystem if not available.

    Args:
        path: The path to the directory to list.
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        A list of files in the directory or an error message.
    """
    logger.debug(f"Listing directory contents for path: {path}")

    result = ls_impl(path, state)
    logger.debug(f"Successfully listed directory: {path}")
    return result


@tool(parse_docstring=True)
def glob(
        pattern: str,
        state: Annotated[dict, InjectedState]
) -> str:
    """Find files matching a glob pattern with fallback support.

    Tries to match against the virtual filesystem in state first, then falls back
    to the local filesystem if not available.

    Args:
        pattern: The glob pattern to match (e.g., "**/*.md").
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        A list of matching file paths or an error message.
    """
    logger.debug(f"Searching for files matching pattern: {pattern}")

    result = glob_impl(pattern, state)
    logger.debug(f"Glob pattern '{pattern}' search completed")
    return result


@tool(parse_docstring=True)
def read_file(
        file_path: str,
        state: Annotated[dict, InjectedState]
) -> str:
    """Read the content of a file with fallback support.

    Tries to read from the virtual filesystem in state first (DeepAgents backend),
    then falls back to the local filesystem if not available.

    For Markdown files, you can read specific sections by appending `#` followed by
    the heading text. Example: `report.md#Introduction` or `docs/guide.md## Installation Steps`.
    The section selector is case-insensitive and matches the exact heading text (including # symbols).

    Args:
        file_path: The path to the file to read. Can include a section selector for markdown files (e.g., 'file.md#Section Title').
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        The content of the file (or specific section if selector provided), or an error message if the file not found.
    """
    logger.debug(f"Reading file: {file_path}")
    try:
        result = read_file_impl(file_path, state)
        logger.debug(f"Successfully read file: {file_path}")
        return result
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        raise


@tool(parse_docstring=True)
def read_doc_folder(
        folder_path: str,
        state: Annotated[dict, InjectedState],
        specific_files: list[str] | None = None,
) -> str:
    """Read and extract text from supported documents in a given folder.

    Use this tool when you need to research from local documents instead of or in addition
    to web search. Supported file types are PDF, text, Markdown, Word, PowerPoint, and Excel.

    If the folder contains a large number of files or the total size is very large,
    this tool will return a summary of the contents instead of all text.
    You can then use the `specific_files` argument to read particular documents of interest.

    Args:
        folder_path: The absolute or relative path to the folder containing document files.
        specific_files: Optional list of filenames within the folder to read specifically.
            If provided, only these files will be processed, bypassing general limits.
        state: LangGraph state (injected automatically, do not supply).

    Returns:
        Extracted text from supported documents, a summary for large folders, or an error message.
    """
    logger.info(f"Reading document folder: {folder_path}, Specific files: {specific_files}")

    result = read_doc_folder_impl(folder_path, specific_files, state)
    logger.info(f"Successfully processed document folder: {folder_path}")
    return result


@tool(parse_docstring=True)
def write_file(
        file_path: str,
        content: str,
        state: Annotated[dict, InjectedState],
) -> str:
    """Write content to a file.

    Use this tool to save research findings, reports, or any text content to a file.
    This tool will overwrite existing files if they exist.

    Args:
        file_path: The path where the file should be written (e.g., 'report.md', './output/findings.txt').
        content: The text content to write to the file.

    Returns:
        Confirmation message with the file path and size, or an error message.
    """
    logger.info(f"Writing file: {file_path} ({len(content)} bytes)")

    content = re.sub(r'/raw/([A-Za-z0-9._\-]+)\.(pdf|docx|pptx|xlsx)\.(md|txt)\b', r'/\1.\2', content)
    # Also handle references to /raw/ without the trailing .md if any
    content = re.sub(r'/raw/([A-Za-z0-9._\-]+\.(?:pdf|docx|pptx|xlsx))\b', r'/\1', content)

    result = write_file_impl(file_path, content)
    logger.info(f"Successfully wrote file: {file_path}")
    return result


# --- Thinking Tool ---

@tool(parse_docstring=True)
def think_tool(
        reflection: str,
) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings - What concrete information have I gathered?
    2. Gap assessment - What crucial information is still missing?
    3. Quality evaluation - Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision - Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    logger.info("Think tool invoked - recording research reflection")
    # Ensure output directory exists for logging reflections
    reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
    output_dir = Path(reports_output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Log the reflection to a dedicated research log file
    now = datetime.now()
    log_file = output_dir / f"research_reflection.log"
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] REFLECTION:\n{reflection}\n")
        f.write("-" * 80 + "\n")
    logger.info(f"Reflection logged to file: {log_file}")

    # Also save reflection to state using send_files_to_state
    try:
        reflection_content = f"# Research Reflection\n\n**Timestamp:** {timestamp}\n\n---\n\n{reflection}\n"
        send_files_to_state({"/research_reflection.md": create_file_data(reflection_content)})
        logger.info("Reflection saved to state: /research_reflection.md")
    except Exception as e:
        logger.warning(f"Could not save reflection to state: {e}")

    return f"Reflection recorded: {reflection}"


# --- Skill-related Tools ---

@tool
def list_available_skills() -> str:
    """List available legacy skills (golden-dataset, frontend-slides) with their descriptions.

    Migrated skills are auto-discovered by the system and do not appear in this list.
    """
    logger.debug("Listing available skills")
    registry = get_skill_registry()
    summaries = registry.get_all_summaries()

    if not summaries:
        logger.warning("No skills are currently available")
        return "No skills are currently available."

    output = "Available skills:\n"
    for summary in summaries:
        output += f"- **{summary['name']}**: {summary['description']}\n"
    logger.debug(f"Found {len(summaries)} available skills")
    return output


@tool(parse_docstring=True)
def read_skill_supporting_file(skill_id: str, filename: str) -> str:
    """Read a supporting file from a skill directory.

    Use this tool when a skill's instructions reference supporting files like
    CSS templates, style presets, or other resources. The skill instructions
    will tell you which files to read.

    Args:
        skill_id: The skill identifier (e.g., 'frontend-slides', 'golden-dataset')
        filename: The name of the supporting file to read.
    """
    logger.debug(f"Reading supporting file '{filename}' from skill '{skill_id}'")
    registry = get_skill_registry()
    content = registry.read_supporting_file(skill_id, filename)

    if content is None:
        logger.warning(f"File '{filename}' not found in skill '{skill_id}'")
        skill_info = registry.get_skill_info(skill_id)
        if not skill_info:
            logger.error(f"Skill '{skill_id}' not found")
            return f"Error: Skill '{skill_id}' not found."

        available_files = [f.name for f in skill_info.path.iterdir() if f.is_file()]
        logger.debug(f"Available files in skill '{skill_id}': {available_files}")
        return (
            f"Error: File '{filename}' not found in skill '{skill_id}'.\n"
            f"Available files: {', '.join(available_files)}"
        )
    logger.debug(f"Successfully read supporting file '{filename}' from skill '{skill_id}'")
    return content


# --- Result Rendering Tools ---

@tool(parse_docstring=True)
def render_skill_output(
        skill_id: str,
        payload_json: str | dict,
) -> str:
    """Render structured skill output for legacy skills (golden-dataset only).

    Use this tool ONLY for the golden-dataset structured output skill.
    DO NOT use this tool for other skills — use write_file to save output directly.
    Provide the skill id and a JSON payload that matches the skill schema exactly.
    The payload may be either a JSON object string or a dict-like JSON object.
    NEVER put raw markdown into payload_json.

    Args:
        skill_id: The skill definition id to use for validation and rendering (golden-dataset).
        payload_json: A JSON object string or dict matching the skill schema.

    Returns:
        Rendered markdown output or a validation error message.
    """
    logger.info(f"Rendering skill output for skill: {skill_id}")

    result = render_skill_output_impl(skill_id, payload_json)
    logger.info(f"Successfully rendered output for skill: {skill_id}")
    return result


# --- Golden Dataset Tools ---


@tool(parse_docstring=True)
def finalize_golden_dataset_output(
        payload_json: str | dict,
        state: Annotated[dict, InjectedState],
) -> str:
    """Export a validated golden-dataset JSON payload to CSV and run quality metrics.

    For the ``golden-dataset`` skill, call this after ``render_skill_output`` with the
    same ``payload_json`` to get the final CSV and quality report.
    It also generates:
    - `/golden_dataset_metrics.md`: Markdown table of all items with quality metrics
    - `/final_report.md`: Comprehensive report of the entire golden dataset generation process

    Args:
        payload_json: A string containing the validated JSON payload, or a dictionary object.
        state: LangGraph state (injected automatically).

    Returns:
        A confirmation message with paths to the generated files.
    """
    logger.info("Finalizing golden dataset output")

    # Handle both string and dict inputs for flexibility
    if isinstance(payload_json, dict):
        logger.debug("Converting dict payload to JSON string")
        payload_json_str = json.dumps(payload_json)
    elif isinstance(payload_json, str):
        payload_json_str = payload_json
    else:
        logger.error(f"Invalid payload_json type: {type(payload_json)}")
        return f"Error: payload_json must be a string or dict, got {type(payload_json).__name__}"

    try:
        payload = robust_json_loads(payload_json_str)
        logger.debug("Successfully parsed golden dataset JSON payload")
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.error(f"Invalid JSON in payload_json: {e}")
        return f"Error: Invalid JSON in payload_json: {e}"

    reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
    output_folder = Path(reports_output_folder)
    logger.info(f"Exporting golden dataset CSV to: {output_folder}")
    csv_path = export_golden_dataset_csv(payload, output_folder)
    logger.info(f"CSV exported to: {csv_path}")

    chat_elapsed_seconds = None
    if isinstance(state, dict):
        # Prefer middleware-computed elapsed time if available.
        elapsed_from_state = state.get("chat_elapsed_seconds")
        if isinstance(elapsed_from_state, (int, float)):
            chat_elapsed_seconds = float(elapsed_from_state)
        else:
            # Fallback to start-time calculation when elapsed value is not present.
            chat_start_time = state.get("chat_start_time")
            if isinstance(chat_start_time, (int, float)):
                chat_elapsed_seconds = datetime.now().timestamp() - float(chat_start_time)

    if isinstance(chat_elapsed_seconds, float):
        logger.debug(f"Chat elapsed time: {chat_elapsed_seconds:.2f} seconds")

    logger.info("Evaluating golden dataset and generating quality metrics")
    metrics_csv_path, markdown_content, final_report_content = (
        evaluate_and_report_golden_dataset(
            csv_path, payload, chat_elapsed_seconds
        )
    )
    logger.info(f"Quality metrics generated - Metrics CSV: {metrics_csv_path}")

    # Write the final humanized report to a file
    report_filename = f"{csv_path.stem}_report.md"
    logger.info(f"Writing final report: {report_filename}")
    report_filepath = write_content_to_output_folder(
        report_filename, final_report_content
    )
    logger.info(f"Final report saved to: {report_filepath}")

    # Persist files to LangGraph state via the channel API so they
    # survive the node boundary (direct state["files"] mutation doesn't).
    return_msg = "\n"
    try:
        send_files_to_state({
            "/golden_dataset_metrics.md": create_file_data(markdown_content),
            "/final_report.md": create_file_data(final_report_content),
        })
        return_msg = "- Note: /golden_dataset_metrics.md, /final_report.md are saved in sandbox\n\n"
        logger.info("Persisted golden dataset files to state")
    except Exception as e:
        logger.warning(f"Could not persist files to state: {e}")

    logger.info("Golden dataset finalization completed successfully")
    return (
        f"Successfully exported and evaluated the golden dataset.\n"
        f"- Raw data saved to: {normalize_path_for_filesystem_tools(str(csv_path))}\n"
        f"- Metrics saved to: {normalize_path_for_filesystem_tools(str(metrics_csv_path))}\n"
        f"- Final report saved to: {report_filepath}\n"
        f"{return_msg}"
        f"## Golden Dataset Quality Metrics\n\n{markdown_content}"
    )
