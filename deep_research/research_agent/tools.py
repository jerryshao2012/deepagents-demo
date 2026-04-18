"""Tools for the research agent."""

import glob as py_glob
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import create_file_data
from dotenv import load_dotenv
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from tavily import TavilyClient

from research_agent.skill_registry import SkillRegistry
from research_agent.skills.golden_dataset.pipeline import (
    evaluate_golden_dataset_csv_file,
    export_golden_dataset_csv,
    evaluate_and_report_golden_dataset,
)
from research_agent.utils.result_rendering import (  # noqa: F401
    render_target_output,
)

# Load environment variables
load_dotenv()

# Constants
REPORTS_OUTPUT_FOLDER = os.environ.get("REPORTS_OUTPUT_FOLDER", "./output")

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
    """Read the content of a file at the given path.

    Args:
        file_path: The path of the file to read.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


@tool(parse_docstring=True)
def ls(path: str) -> str:
    """List the contents of a directory.

    Args:
        path: The directory path to list.
    """
    try:
        return "\n".join(os.listdir(path))
    except Exception as e:
        return f"Error listing directory: {e}"


@tool(parse_docstring=True)
def glob(pattern: str) -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: The glob pattern to search for.
    """
    try:
        return "\n".join(py_glob.glob(pattern, recursive=True))
    except Exception as e:
        return f"Error with glob: {e}"


@tool(parse_docstring=True)
def read_doc_folder(
        folder_path: str | None = None, state: Annotated[dict, InjectedState] = None
) -> str:
    """Read all text files in the document folder and return their concatenated content.

    Args:
        folder_path: The path to the document folder.
        state: LangGraph state (injected automatically).
    """
    if folder_path is None:
        if state and state.get("doc_folder"):
            folder_path = state["doc_folder"]
        elif os.environ.get("DOC_FOLDER"):
            folder_path = os.environ["DOC_FOLDER"]

    if folder_path is None:
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
    """Search the web for the given query using the Tavily API.

    Args:
        query: The search query.
    """
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

    Args:
        thought: The thought, reflection, or plan to record.
    """
    return f"Your thought has been recorded: '{thought}'"


# --- Skill-related Tools ---

@tool
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


# --- Golden Dataset Tools ---

def write_content_to_output_folder(filename: str, content: str) -> str:
    """Write content to a file in the output folder."""
    output_subfolder = Path(REPORTS_OUTPUT_FOLDER)
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

    output_folder = Path(REPORTS_OUTPUT_FOLDER)
    csv_path = export_golden_dataset_csv(payload, output_folder)

    agent_start_time = state.get("agent_start_time") if state else None
    if isinstance(agent_start_time, float):
        elapsed_seconds = datetime.now().timestamp() - agent_start_time
    else:
        elapsed_seconds = 0.0

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


# --- Frontend Slides Tools ---

@tool("frontend-slides", parse_docstring=True)
def frontend_slides(
        presentation_markdown: str,
        output_filename: str | None = None,
        deck_title: str | None = None,
        style_preset: str = "Creative Voltage",
        animation_feeling: str = "professional",
        enable_inline_editing: bool = False,
        state: Annotated[dict, InjectedState] = None,
) -> str:
    """Generate a self-contained HTML slide deck from markdown-style slide content.

    Use this tool when the user wants an actual browser-ready presentation rather than
    plain markdown. It accepts content in the frontend-slides format, such as:
    ``# [Slide 1] Title: ...`` followed by ``**Headline:**``, ``**Subtitle:**``,
    ``**Body:**``, bullet lists, and optional ``**Callout:**`` blocks.

    **Before calling this tool, read these supporting files for guidance:**
    - Use `read_skill_supporting_file('frontend_slides', 'html-template.md')` to understand HTML architecture
    - Use `read_skill_supporting_file('frontend_slides', 'animation-patterns.md')` for animation reference
    - Use `read_skill_supporting_file('frontend_slides', 'viewport-base.css')` for mandatory CSS rules

    These files provide the architectural patterns and best practices you should follow when
    structuring your presentation content and choosing animation styles.

    Args:
        presentation_markdown: Markdown-style slide content to convert into HTML slides.
        output_filename: Optional filename for the generated HTML. Saved under OUTPUT_FOLDER.
        deck_title: Optional browser title for the presentation. Defaults to the first slide title.
        style_preset: Visual preset name. Supported: Bold Signal, Electric Studio, Creative Voltage, Dark Botanical, Notebook Tabs, Pastel Geometry, Split Pastel, Vintage Editorial, Neon Cyber, Terminal Green, Swiss Modern, Paper & Ink.
        animation_feeling: Animation style feeling. Options: dramatic (cinematic), techy (futuristic), playful (bouncy), professional (subtle), calm (gentle), editorial (staggered).
        enable_inline_editing: Whether to include in-browser text editing capabilities. Options: True / False.
        state: LangGraph state (injected automatically, do not supply).

    Returns:
        str: Confirmation containing the generated file path and slide count, or an error message.
    """
    from research_agent.skills.frontend_slides.pipeline import _parse_sections, _build_html, _slugify_filename

    # Parse the markdown content into structured slide data
    slides = _parse_sections(presentation_markdown)
    if not slides:
        return (
            "Error: No slides were detected. Use headings like:\n"
            "- `# [Slide 1] Title: My Slide` (explicit numbering)\n"
            "- `## Slide 1: My Slide` (alternative format)\n"
            "- `# My Slide Title` (plain heading, auto-numbered)\n"
            "Separate slides with `---` on a new line."
        )

    # Build HTML using the template engine with dynamic resources
    resolved_title = deck_title or str(slides[0]["title"])
    html_content = _build_html(resolved_title, slides, style_preset, animation_feeling, enable_inline_editing)

    # Determine safe filename
    if output_filename:
        safe_name = Path(output_filename).name
        if not safe_name.endswith(".html"):
            safe_name = f"{safe_name}.html"
    else:
        safe_name = f"{_slugify_filename(resolved_title)}.html"

    # Save to BOTH output folders: ./output and ./reports
    output_folder = Path(REPORTS_OUTPUT_FOLDER)
    output_folder.mkdir(parents=True, exist_ok=True)
    output_path = output_folder / safe_name
    output_path.write_text(html_content, encoding="utf-8")

    reports_path = output_folder / safe_name
    reports_path.write_text(html_content, encoding="utf-8")

    # Update state if available
    if state is not None:
        try:
            files = state.get("files", {})
            files[f"/{safe_name}"] = create_file_data(html_content)
            state["files"] = files
        except ImportError:
            # Fallback: manually create file data structure
            files = state.get("files", {})
            files[f"/{safe_name}"] = {
                "content": html_content,
                "type": "text/html",
            }
            state["files"] = files

    normalized_output_path = _normalize_path_for_filesystem_tools(str(output_path))
    normalized_reports_path = _normalize_path_for_filesystem_tools(str(reports_path))
    return (
        f"Generated `{style_preset}` HTML presentation with {len(slides)} slide(s).\n"
        f"- Saved to output folder: `{normalized_output_path}`\n"
        f"- Saved to reports folder: `{normalized_reports_path}`"
    )


@tool("frontend-slides-export-pdf", parse_docstring=True)
def frontend_slides_export_pdf(
        html_file_path: str,
        output_pdf_path: str | None = None,
        compact: bool = False,
) -> str:
    """Export an HTML presentation to PDF.

    Use this tool when the user wants to convert a generated HTML presentation into a PDF file.
    This calls the `scripts/export-pdf.sh` script, which uses Playwright to capture screenshots
    of each slide and compile them. Note that animations are not preserved in the PDF.

    Args:
        html_file_path: The absolute path to the generated HTML presentation file.
        output_pdf_path: Optional absolute path for the output PDF. If not provided, it saves next to the HTML file.
        compact: Whether to render the PDF in compact mode (1280x720 instead of 1920x1080) for smaller file sizes.

    Returns:
        str: The path to the generated PDF file or an error message.
    """
    from research_agent.skills.frontend_slides.pipeline import _SKILL_DIR

    script_path = _SKILL_DIR / "scripts" / "export-pdf.sh"

    cmd = ["bash", str(script_path), html_file_path]
    if output_pdf_path:
        cmd.append(output_pdf_path)
    if compact:
        cmd.append("--compact")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully exported PDF.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error exporting PDF: {e.stderr}\\n\\n{e.stdout}"


@tool("frontend-slides-deploy", parse_docstring=True)
def frontend_slides_deploy(
        html_file_path: str,
) -> str:
    """Deploy an HTML presentation to a live Vercel URL.

    Use this tool when the user wants to share the presentation online.
    This calls the `scripts/deploy.sh` script which deploys the presentation to Vercel.
    The user must have Vercel CLI installed and be logged in.

    Args:
        html_file_path: The absolute path to the generated HTML presentation file or directory.

    Returns:
        str: The deployment output including the live URL, or an error message.
    """
    from research_agent.skills.frontend_slides.pipeline import _SKILL_DIR

    script_path = _SKILL_DIR / "scripts" / "deploy.sh"

    cmd = ["bash", str(script_path), html_file_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully deployed presentation.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error deploying presentation: {e.stderr}\\n\\n{e.stdout}"


@tool("frontend-slides-extract-pptx", parse_docstring=True)
def frontend_slides_extract_pptx(
        pptx_file_path: str,
        output_dir: str | None = None,
) -> str:
    """Extract content and images from a PowerPoint (.pptx) file.

    Use this tool when the user provides a .pptx file and wants to convert it
    into an HTML presentation. This runs `scripts/extract-pptx.py` which returns
    a JSON structure containing slides, text, and images.

    Args:
        pptx_file_path: The absolute path to the input PowerPoint file.
        output_dir: Optional absolute path to the directory where extracted data and images should be saved.

    Returns:
        str: The output of the extraction process, including the path to the extracted JSON.
    """
    from research_agent.skills.frontend_slides.pipeline import _SKILL_DIR

    script_path = _SKILL_DIR / "scripts" / "extract-pptx.py"

    cmd = ["python3", str(script_path), pptx_file_path]
    if output_dir:
        cmd.append(output_dir)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return f"Successfully extracted PowerPoint content.\\n\\n{result.stdout}"
    except subprocess.CalledProcessError as e:
        return f"Error extracting PowerPoint content: {e.stderr}\\n\\n{e.stdout}"
