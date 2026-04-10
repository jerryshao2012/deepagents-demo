"""Research Tools.

This module provides search and content processing utilities for the research agent,
using Tavily for URL discovery and fetching full webpage content.
"""

from __future__ import annotations

import datetime
import os
import random
import re
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import create_file_data
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from research_agent.utils.content_extractors import _extract_supported_document
# Import modularized utilities and tools
from research_agent.utils.knowledge_filesystem import (  # noqa: F401
    MAX_GLOB_DEPTH,
    MAX_FILES_TO_READ,
    MAX_TOTAL_SIZE_MB,
    SUPPORTED_DOC_SUFFIXES,
    REPORTS_OUTPUT_FOLDER,
    _folder_listing_cache,
    _normalize_path_for_filesystem_tools,
    _get_extracted_path,
    _resolve_doc_output_subfolder,
    ls,
    glob,
    read_file,
)
from research_agent.utils.result_rendering import (  # noqa: F401
    _prepare_validated_payload,
    render_target_output,
)
from research_agent.utils.web_search import (  # noqa: F401
    tavily_search,
)


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps systematically.
    This creates a deliberate pause in the research workflow for quality decision-making.

    Args:
        reflection: Detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


@tool(parse_docstring=True)
def read_doc_folder(
        folder_path: str,
        specific_files: list[str] | None = None,
        state: Annotated[dict, InjectedState] = None,
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
    configured_doc_folder: str | None = None
    if state and isinstance(state, dict):
        configured_doc_folder = state.get("doc_folder")

    # Fallback: subagent state schemas may not include doc_folder, so the
    # orchestrator also persists it as an environment variable.
    if not configured_doc_folder:
        configured_doc_folder = os.environ.get("DOC_FOLDER")

    if not configured_doc_folder:
        return (
            "Error: No document folder has been configured for this research task. "
            "Pass --doc-folder <path> when invoking the CLI, or include the folder path "
            "(e.g. '--doc-folder ./docs/policy/') in your message when using the API. "
            "Do NOT attempt to read from any other filesystem path."
        )

    allowed_root = Path(configured_doc_folder).resolve()
    folder = Path(folder_path).resolve()
    try:
        folder.relative_to(allowed_root)
    except ValueError:
        print(
            f"[read_doc_folder] Redirecting '{folder_path}' → '{allowed_root}' (only the configured doc_folder is permitted).")
        folder = allowed_root

    if not folder.exists(): return f"Error: Folder '{folder}' does not exist."
    if not folder.is_dir(): return f"Error: '{folder}' is not a directory."

    specific_set = set(specific_files) if specific_files else None

    # Cached folder listing
    cache_key = str(folder.resolve())
    if cache_key in _folder_listing_cache:
        supported_files = _folder_listing_cache[cache_key]
    else:
        all_candidates: list[Path] = []
        for file_path in folder.rglob("*"):
            if len(file_path.relative_to(folder).parts) > MAX_GLOB_DEPTH:
                continue
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_DOC_SUFFIXES:
                all_candidates.append(file_path)
        supported_files = sorted(all_candidates)
        _folder_listing_cache[cache_key] = supported_files

    if not supported_files:
        return f"No supported document files found in {folder_path}. Supported types: .pdf, .txt, .md, .docx, .pptx, .xlsx."

    if specific_set:
        files_to_process = [f for f in supported_files if f.name in specific_set]
        if not files_to_process:
            return f"None of the requested files were found in {folder_path}. Available: {', '.join(f.name for f in supported_files[:10])}..."
    else:
        total_files = len(supported_files)
        total_size_mb = sum(f.lstat().st_size for f in supported_files) / (1024 * 1024)

        if total_files > MAX_FILES_TO_READ or total_size_mb > MAX_TOTAL_SIZE_MB:
            avg_size_mb = total_size_mb / total_files if total_files > 0 else 0
            max_files_by_size = max(1, int(MAX_TOTAL_SIZE_MB / avg_size_mb)) if avg_size_mb > 0 else MAX_FILES_TO_READ
            sample_size = min(MAX_FILES_TO_READ, total_files, max_files_by_size)
            auto_sample = [f.name for f in random.sample(supported_files, sample_size)]
            preview_list = "\n".join(f"- {f.name} ({f.lstat().st_size / 1024:.1f} KB)" for f in supported_files[:60])
            if total_files > 60: preview_list += f"\n... and {total_files - 60} more files (not shown)."
            auto_sample_str = ", ".join(f'"{n}"' for n in auto_sample)
            return (
                f"TOOL RESULT — folder too large to read all at once: {total_files} files, {total_size_mb:.1f} MB (limits: {MAX_FILES_TO_READ} files / {MAX_TOTAL_SIZE_MB} MB).\n\n"
                "ACTION REQUIRED — do NOT ask the user for confirmation. You MUST immediately:\n"
                f"1. Call read_doc_folder again on '{folder_path}' with specific_files set to the auto-sample below.\n"
                "2. Continue research using those documents.\n\n"
                f"Pre-built diverse auto-sample ({len(auto_sample)} files, evenly spread across the directory):\n"
                f"[{auto_sample_str}]\n\n"
                f"Full file listing (first 60 of {total_files}):\n{preview_list}"
            )
        files_to_process = supported_files

    extracted_text: list[str] = []
    processed_files: list[str] = []
    failed_files: list[str] = []
    output_subfolder = _resolve_doc_output_subfolder(folder)

    for file_path in files_to_process:
        target_path = _get_extracted_path(file_path, output_subfolder)
        if target_path.exists():
            print(f"Skipping {file_path.name}, already extracted to {target_path}")
            try:
                content = target_path.read_text(encoding="utf-8")
                processed_files.append(f"{file_path.name} (skipped, loaded from {target_path})")
                extracted_text.append(f"--- Content of {file_path.name} (from cache) ---\n{content}\n")
                continue
            except Exception as exc:
                print(f"Failed to read existing extract {target_path}: {exc}. Re-extracting...")

        print(f"Processing document: {file_path.name}...")
        try:
            content = _extract_supported_document(file_path)
            saved_path = _save_extracted_content(file_path, content, output_folder=output_subfolder)
            processed_files.append(f"{file_path.name} (saved to {saved_path})")
            extracted_text.append(f"--- Content of {file_path.name} ---\n{content}\n")
        except Exception as exc:
            failed_files.append(file_path.name)
            extracted_text.append(f"--- Error reading {file_path.name}: {exc} ---\n")

    summary_lines = [f"Processed {len(processed_files)}/{len(files_to_process)} supported file(s) from {folder}."]
    if processed_files: summary_lines.append(f"Files processed: {', '.join(processed_files)}")
    if failed_files: summary_lines.append(f"Files failed: {', '.join(failed_files)}")
    summary_lines.append(
        "\nIMPORTANT: Use ONLY the file paths listed above. Do NOT reference "
        "filenames from the user's prompt if they differ from the actual files "
        "discovered here. If you need to read individual files, use the exact "
        "paths shown in 'Files processed' above with the `read_file` tool."
    )
    print("\n".join(summary_lines))
    return "\n".join(summary_lines + [""] + extracted_text)


def _save_extracted_content(original_file_path: Path, content: str, output_folder: Path | None = None) -> str:
    if output_folder:
        output_dir = output_folder
    else:
        output_dir = Path(REPORTS_OUTPUT_FOLDER)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = _get_extracted_path(original_file_path, output_dir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return _normalize_path_for_filesystem_tools(str(file_path))


def save_research_report(report_title: str, content: str) -> str:
    """Save a research report to the output folder."""
    output_subfolder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
    output_subfolder.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^a-zA-Z0-9_\- ]", "", report_title).strip()[:100]
    safe_title = safe_title.replace(" ", "_")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{safe_title}.md"
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
    same JSON. This writes the CSV under the output folder and runs metrics in one step.
    It also generates:
    - `/golden_dataset_metrics.md`: Markdown table of all items with quality metrics
    - `/final_report.md`: Comprehensive report of the entire golden dataset generation process

    Args:
        payload_json: JSON object matching the golden-dataset schema (same payload as ``render_target_output``).
        state: LangGraph state

    Returns:
        Paths to the exported CSV and metrics output, or a validation or runtime error message.
    """
    import time
    from research_agent.skills.golden_dataset.pipeline import (
        GOLDEN_DATASET_TARGET_ID,
        evaluate_and_report_golden_dataset,
        export_golden_dataset_csv,
    )

    _, payload, err = _prepare_validated_payload(GOLDEN_DATASET_TARGET_ID, payload_json)
    if err: return err
    if payload is None:
        return "Error: Failed to prepare validated payload"

    try:
        start_time = state.get("agent_start_time") if state else None
        if isinstance(start_time, float):
            elapsed_seconds = time.time() - start_time
        else:
            elapsed_seconds = 0.0
        output_subfolder = Path(os.environ.get("OUTPUT_FOLDER") or REPORTS_OUTPUT_FOLDER)
        csv_path = export_golden_dataset_csv(payload, output_subfolder)
        metrics_csv_path, markdown_content, final_report_content = evaluate_and_report_golden_dataset(
            csv_path=csv_path, payload=payload, output_folder=output_subfolder, elapsed_seconds=elapsed_seconds
        )
        metrics_md_path = output_subfolder / "golden_dataset_metrics.md"
        with open(metrics_md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        final_report_path = output_subfolder / "final_report.md"
        with open(final_report_path, "w", encoding="utf-8") as f:
            f.write(final_report_content)
        if state is not None:
            files = state.get("files", {})
            files["/golden_dataset_metrics.md"] = create_file_data(markdown_content)
            files["/final_report.md"] = create_file_data(final_report_content)
            state["files"] = files
        return (
            f"**CSV exported to:** `{csv_path}`\n\n**Metrics CSV:** `{metrics_csv_path}`\n\n"
            f"**Metrics Markdown:** `{metrics_md_path}`\n\n**Final Report:** `{final_report_path}`\n\n"
            f"All files have been generated successfully!"
        )
    except Exception as e:
        return f"**Error exporting or evaluating golden dataset:** {e}"


@tool(parse_docstring=True)
def trigger_dataset_evaluation(file_path: str) -> str:
    """Evaluate a generated golden dataset CSV to compute quality metrics.

    Run this tool only after you have successfully generated a golden dataset
    and received the CSV file path locally in your output folder. This runs a heavy
    evaluation script to compute Similarity, Relevance, Coherence, and Groundedness.

    For new datasets, prefer ``finalize_golden_dataset_output``, which exports the CSV
    and runs this evaluation in order. Use this tool to re-run metrics on an existing CSV.

    Args:
        file_path: The path to the CSV file to evaluate (e.g., "./output/golden_dataset.csv").

    Returns:
        The result of the quality metric evaluation, including the path to the scored dataset.
    """
    from research_agent.skills.golden_dataset.pipeline import evaluate_golden_dataset_csv_file
    return evaluate_golden_dataset_csv_file(file_path)
