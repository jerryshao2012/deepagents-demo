"""Tools for the research agent."""

from datetime import datetime
import glob as py_glob
import json
import os
from pathlib import Path
from typing import Annotated

from langchain_core.tools import InjectedState, tool
from tavily import TavilyClient

from deep_research.research_agent.skill_registry import SkillRegistry
from deep_research.research_agent.skills.frontend_slides.pipeline import (
    frontend_slides,
)
from deep_research.research_agent.skills.golden_dataset.pipeline import (
    evaluate_golden_dataset_csv_file,
    export_golden_dataset_csv,
    evaluate_and_report_golden_dataset,
)

# Constants
REPORTS_OUTPUT_FOLDER = "reports"

# --- Skill Registry Singleton ---
_skill_registry_instance: SkillRegistry | None = None


def _get_skill_registry() -> SkillRegistry:
    """Get or create the skill registry instance."""
    global _skill_registry_instance
    if _skill_registry_instance is None:
        from pathlib import Path
        skills_dir = Path(__file__).parent / "skills"
        _skill_registry_instance = SkillRegistry(skills_dir)
    return _skill_registry_instance


# --- Filesystem Tools ---

def _normalize_path_for_filesystem_tools(file_path: str) -> str:
    """Normalize file paths for filesystem tools compatibility."""
    return file_path.replace("\\", "/")


@tool(parse_docstring=True)
def read_file(file_path: str) -> str:
    """Read the content of a file at the given path."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


@tool(parse_docstring=True)
def ls(path: str) -> str:
    """List the contents of a directory."""
    try:
        return "\n".join(os.listdir(path))
    except Exception as e:
        return f"Error listing directory: {e}"


@tool(parse_docstring=True)
def glob(pattern: str) -> str:
    """Find files matching a glob pattern."""
    try:
        return "\n".join(py_glob.glob(pattern, recursive=True))
    except Exception as e:
        return f"Error with glob: {e}"


@tool(parse_docstring=True)
def read_doc_folder(
        folder_path: str | None = None, state: Annotated[dict, InjectedState] = None
) -> str:
    """Read all text files in the document folder and return their concatenated content."""
    if folder_path is None:
        if state and state.get("doc_folder"):
            folder_path = state["doc_folder"]
        elif os.environ.get("DOC_FOLDER"):
            folder_path = os.environ["DOC_FOLDER"]
        else:
            return "Error: No document folder specified in the agent state or environment."

    try:
        path = Path(folder_path)
        if not path.is_dir():
            return f"Error: The path {folder_path} is not a valid directory."

        content = []
        for file_path in path.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in [
                ".txt",
                ".md",
                ".py",
                ".json",
                ".xml",
                ".html",
                ".css",
                ".js",
            ]:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content.append(f"--- {file_path.name} ---\n{f.read()}")
                except Exception:
                    pass  # Ignore files that can't be read
        return "\n\n".join(content)
    except Exception as e:
        return f"Error reading document folder: {e}"


# --- Web Search Tool ---

@tool(parse_docstring=True)
def tavily_search(query: str) -> str:
    """Search the web for the given query using the Tavily API."""
    try:
        client = TavilyClient(os.environ["TAVILY_API_KEY"])
        response = client.search(query, search_depth="advanced")
        return json.dumps(response["results"])
    except Exception as e:
        return f"Error searching with Tavily: {e}"


# --- Thinking Tool ---

@tool(parse_docstring=True)
def think_tool(thought: str) -> str:
    """
    Use this tool to write down your thoughts, reflections, and plans.
    This helps you keep track of your reasoning and debug your thought process.
    For example:
    - "I need to find out the capital of France. I will use the search tool for that."
    - "The user wants a summary of the document. I will first read the file and then summarize it."
    - "I have received an error. I should analyze the error and try a different approach."
    """
    return f"Your thought has been recorded: '{thought}'"


# --- Skill-related Tools ---

@tool(parse_docstring=True)
def list_available_skills() -> str:
    """List all available skills with their descriptions."""
    registry = _get_skill_registry()
    summaries = registry.get_all_summaries()

    if not summaries:
        return "No skills are currently available."

    output = "Available skills:\n"
    for summary in summaries:
        output += f"- **{summary['name']}**: {summary['description']}\n"
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
    registry = _get_skill_registry()
    content = registry.read_supporting_file(skill_id, filename)

    if content is None:
        skill_info = registry.get_skill_info(skill_id)
        if not skill_info:
            return f"Error: Skill '{skill_id}' not found."

        available_files = [f.name for f in skill_info.path.iterdir() if f.is_file()]
        return (
            f"Error: File '{filename}' not found in skill '{skill_id}'.\n"
            f"Available files: {', '.join(available_files)}"
        )
    return content


@tool(parse_docstring=True)
def render_target_output(
        payload_json: str, state: Annotated[dict, InjectedState] = None
) -> str:
    """Render the final markdown output for a given target and its validated JSON payload.

    This is the final step for any research task that has a specific ``--target``.
    The tool loads the target's skill, validates the JSON against the skill's
    schema, and renders the final markdown output using the skill's template.

    Args:
        payload_json: A string containing the validated JSON payload to render.
        state: LangGraph state (injected automatically).

    Returns:
        The rendered markdown output, or an error message if rendering fails.
    """
    target = state.get("target") if state else None
    if not target:
        return "Error: No target specified in the agent state. Cannot render output."

    registry = _get_skill_registry()
    try:
        payload = json.loads(payload_json)
        output = registry.render_skill_output(target, payload)
        return output
    except Exception as e:
        return f"Error rendering output for target '{target}': {e}"


# --- Golden Dataset Tools ---

def write_content_to_output_folder(filename: str, content: str) -> str:
    """Write content to a file in the output folder."""
    output_subfolder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
    output_subfolder.mkdir(parents=True, exist_ok=True)
    file_path = output_subfolder / filename
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return _normalize_path_for_filesystem_tools(str(file_path))


@tool(parse_docstring=True)
def finalize_golden_dataset_output(
        payload_json: str,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Export a validated golden-dataset JSON payload to CSV and run quality metrics.

    For the ``golden-dataset`` target, call this after ``render_target_output`` with the
    same ``payload_json`` to get the final CSV and quality report.

    Args:
        payload_json: A string containing the validated JSON payload.
        state: LangGraph state (injected automatically).

    Returns:
        A confirmation message with paths to the generated files.
    """
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON in payload_json: {e}"

    output_folder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
    csv_path = export_golden_dataset_csv(payload, output_folder)

    agent_start_time = state.get("agent_start_time") if state else None
    elapsed_seconds = (
        (datetime.now().timestamp() - agent_start_time) if agent_start_time else 0.0
    )

    metrics_csv_path, markdown_content, final_report_content = (
        evaluate_and_report_golden_dataset(
            csv_path, payload, output_folder, elapsed_seconds
        )
    )

    # Write the final humanized report to a file
    report_filename = f"{csv_path.stem}_report.md"
    report_filepath = write_content_to_output_folder(
        report_filename, final_report_content
    )

    return (
        f"Successfully exported and evaluated the golden dataset.\n"
        f"- Raw data saved to: {_normalize_path_for_filesystem_tools(str(csv_path))}\n"
        f"- Metrics saved to: {_normalize_path_for_filesystem_tools(str(metrics_csv_path))}\n"
        f"- Final report saved to: {report_filepath}\n\n"
        f"## Golden Dataset Quality Metrics\n\n{markdown_content}"
    )


@tool(parse_docstring=True)
def trigger_dataset_evaluation(file_path: str) -> str:
    """Run quality metrics on an existing golden-dataset CSV file.

    Use this tool if you already have a CSV file and want to evaluate its quality.
    If you are generating a new dataset, prefer using ``finalize_golden_dataset_output``.

    Args:
        file_path: The absolute path to the golden dataset CSV file.

    Returns:
        A confirmation message with the path to the metrics file, or an error message.
    """
    return evaluate_golden_dataset_csv_file(file_path)
