from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import file_data_to_string, create_file_data
from dotenv import load_dotenv
from langgraph.prebuilt import InjectedState

from logger_utils import setup_logger
from research_agent.utils.content_extractors import extract_supported_document

# Load environment variables
load_dotenv()
# These can be configured via environment variables with sensible defaults
MAX_GLOB_DEPTH = int(os.environ.get("MAX_GLOB_DEPTH", "3"))
MAX_FILES_TO_READ = int(os.environ.get("MAX_FILES_TO_READ", "20"))
MAX_TOTAL_SIZE_MB = int(os.environ.get("MAX_TOTAL_SIZE_MB", "50"))

SUPPORTED_DOC_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx", ".xlsx"}

# Global in‑memory cache for folder listings (path → list of Path objects)
_folder_listing_cache: dict[str, list[Path]] = {}

logger = setup_logger(__name__)


def normalize_path_for_filesystem_tools(
        path_str: str
) -> str:
    """Normalize paths for cross-platform compatibility with deepagents filesystem tools.
    
    Deepagents filesystem tools (glob, ls, etc.) expect paths relative to the working directory.
    This function ensures paths start with './' instead of '/' for proper resolution on all platforms.
    
    Args:
        path_str: The path string to normalize
        
    Returns:
        Normalized path string with proper relative prefix
    """
    if not path_str:
        return path_str

    # Convert Windows backslashes to forward slashes for consistency
    normalized = path_str.replace('\\', '/')

    # If it's a real absolute path that exists, return it as-is
    # This is important for tests and cases where the user provides a real absolute path
    if Path(normalized.split('*')[0].split('?')[0]).is_absolute() and Path(
            normalized.split('*')[0].split('?')[0]).exists():
        return normalized

    # If path starts with '/', it's being treated as absolute from root but likely intended as relative to project
    # Convert to relative path by adding './' prefix
    if normalized.startswith('/') and not normalized.startswith('./'):
        normalized = './' + normalized.lstrip('/')
    # Ensure relative paths also start with './' for explicit relative reference
    elif not normalized.startswith('./') and not normalized.startswith('/'):
        normalized = './' + normalized

    return normalized


def write_content_to_output_folder(
        filename: str,
        content: str
) -> str:
    """Write content to a file in the output folder."""
    reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
    output_subfolder = Path(reports_output_folder)
    output_subfolder.mkdir(parents=True, exist_ok=True)
    file_path = output_subfolder / filename
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return normalize_path_for_filesystem_tools(str(file_path))


def _get_extracted_path(
        file_path: Path,
        output_folder: Path
) -> Path:
    """Get the target path for an extracted file."""
    suffix = file_path.suffix.lower()
    if suffix in {".pdf", ".md", ".docx", ".pptx"}:
        new_extension = ".md"
    else:
        new_extension = ".txt"

    new_filename = f"{file_path.name}_extracted{new_extension}"
    return output_folder / "extracted" / new_filename


def _resolve_doc_output_subfolder(
        folder: Path
) -> Path:
    reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
    configured_output = Path(os.environ.get("OUTPUT_FOLDER", reports_output_folder))
    if configured_output.name == folder.name:
        return configured_output
    if configured_output == Path(reports_output_folder):
        return configured_output / folder.name
    return configured_output


def _save_extracted_content(
        original_file_path: Path,
        content: str,
        output_folder: Path | None = None
) -> str:
    if output_folder:
        output_dir = output_folder
    else:
        reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
        output_dir = Path(reports_output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = _get_extracted_path(original_file_path, output_dir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return normalize_path_for_filesystem_tools(str(file_path))


def ls_impl(
        path: str,
        state: Annotated[dict, InjectedState] = None
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
    normalized_path = normalize_path_for_filesystem_tools(path)

    # Try 1: Check virtual filesystem in state (DeepAgents backend)
    if state and "files" in state:
        try:
            dir_files = []

            # Normalize the target directory path for comparison
            norm_dir = normalized_path.rstrip('/').lstrip('./')
            if norm_dir == '':
                norm_dir = '.'

            for file_path in state["files"]:
                # Normalize the file path
                norm_file = file_path.lstrip('/')

                # Get the parent directory of the file
                if '/' in norm_file:
                    parent_dir = '/'.join(norm_file.split('/')[:-1])
                else:
                    parent_dir = '.'

                # Check if file is directly in the target directory
                if parent_dir == norm_dir or parent_dir == normalized_path.rstrip('/'):
                    # Extract just the filename
                    filename = norm_file.split('/')[-1]
                    # Mark directories with trailing slash (we can't determine this from flat file list)
                    dir_files.append(filename)

            if dir_files:
                return "\n".join(sorted(dir_files))
        except Exception as e:
            pass  # Fall through to local filesystem

    # Try 2: Use local filesystem
    normalized_path = normalize_path_for_filesystem_tools(path)
    p = Path(normalized_path)
    if not p.exists():
        return f"Error: Path '{path}' not found"
    if not p.is_dir():
        return f"Error: Path '{path}' is not a directory"

    try:
        files = [f.name + ("/" if f.is_dir() else "") for f in p.iterdir()]
        return "\n".join(sorted(files))
    except Exception as e:
        return f"Error listing directory '{path}': {e}"


def glob_impl(
        pattern: str,
        state: Annotated[dict, InjectedState] = None
) -> str:
    """Implementation of glob pattern matching with fallback support.
    
    Tries to match against the virtual filesystem in state first, then falls back
    to the local filesystem if not available.

    Args:
        pattern: The glob pattern to match (e.g., "**/*.md").
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        A list of matching file paths or an error message.
    """
    normalized_pattern = normalize_path_for_filesystem_tools(pattern)

    # Try 1: Check virtual filesystem in state (DeepAgents backend)
    if state and "files" in state:
        try:
            import fnmatch
            matched_files = []

            for file_path in state["files"]:
                # Normalize the file path for comparison
                norm_file = file_path.lstrip('/')

                # Check if the file matches the pattern
                # Handle different pattern formats
                if fnmatch.fnmatch(norm_file, normalized_pattern.lstrip('./')):
                    matched_files.append(file_path)
                elif fnmatch.fnmatch(norm_file, normalized_pattern):
                    matched_files.append(file_path)
                elif fnmatch.fnmatch(file_path, normalized_pattern):
                    matched_files.append(file_path)

            if matched_files:
                return "\n".join(sorted(matched_files))
        except Exception as e:
            pass  # Fall through to local filesystem

    # Try 2: Use local filesystem
    normalized_pattern = normalize_path_for_filesystem_tools(pattern)

    # If it's a real absolute path or starts with ./, use it
    if normalized_pattern.startswith('./') or (len(normalized_pattern) > 0 and normalized_pattern[0] == '/') or (
            len(normalized_pattern) > 1 and normalized_pattern[1] == ':'):
        # Determine if it's an absolute path from the start
        is_absolute = (len(normalized_pattern) > 0 and normalized_pattern[0] == '/') or (
                len(normalized_pattern) > 1 and normalized_pattern[1] == ':')

        # For glob, we need to split the fixed part from the pattern part
        # We can't just use Path(normalized_pattern) because it might not like wildcards in some OS calls
        if is_absolute:
            # On Unix, parts[0] is '/'
            parts = Path(normalized_pattern.split('*')[0].split('?')[0]).parts
            # Reconstruct the base path from fixed parts
            base_path = Path(*parts)
            # The rest is the pattern
            glob_pattern = normalized_pattern[len(str(base_path)):]
            if glob_pattern.startswith('/'):
                glob_pattern = glob_pattern[1:]
            if not glob_pattern:
                glob_pattern = "*"
        else:
            path_obj = Path(normalized_pattern)
            parts = path_obj.parts
            fixed_parts = []
            pattern_parts = []
            found_wildcard = False
            for part in parts:
                if '*' in part or '?' in part:
                    found_wildcard = True
                if found_wildcard:
                    pattern_parts.append(part)
                else:
                    fixed_parts.append(part)

            if not fixed_parts:
                base_path = Path(".")
            else:
                base_path = Path(*fixed_parts)

            glob_pattern = "/".join(pattern_parts) if pattern_parts else "*"
    else:
        # Fallback for simple patterns or relative patterns without ./
        if "/" in normalized_pattern:
            base_path_str, glob_pattern = normalized_pattern.rsplit("/", 1)
            if not glob_pattern:  # case like "path/to/dir/"
                glob_pattern = "*"
            base_path = Path(base_path_str)
        else:
            base_path = Path(".")
            glob_pattern = normalized_pattern

    if not base_path.exists():
        return f"Error: Base path for pattern '{pattern}' not found"

    try:
        # If it's a recursive glob, handle it
        matches = list(base_path.glob(glob_pattern))
        return "\n".join(sorted(str(m.relative_to(base_path)) for m in matches))
    except Exception as e:
        return f"Error running glob for pattern '{pattern}': {e}"


def read_file_impl(
        file_path: str,
        state: Annotated[dict, InjectedState] = None
) -> str:
    """Implementation of file reading with fallback support.
    
    Tries to read from the virtual filesystem in state first (DeepAgents backend),
    then falls back to the local filesystem if not available.

    Args:
        file_path: The path to the file to read.
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        The content of the file or an error message if the file not found.
    """
    # Normalize path first for consistent comparison across both filesystems
    normalized_path = normalize_path_for_filesystem_tools(file_path)

    # Try 1: Check state["files"] for virtual filesystem (DeepAgents backend)
    if state and "files" in state:
        # Try exact match with original path first
        if file_path in state["files"]:
            try:
                file_content = file_data_to_string(state["files"][file_path])
                return file_content
            except Exception:
                pass  # Fall through to other attempts

        # Try normalized path
        if normalized_path in state["files"]:
            try:
                file_content = file_data_to_string(state["files"][normalized_path])
                return file_content
            except Exception:
                pass  # Fall through to other attempts

        # Try additional normalized variants for maximum compatibility
        normalized_variants = [
            normalized_path.lstrip('/'),
            '/' + normalized_path.lstrip('/'),
            './' + normalized_path.lstrip('./'),
        ]

        for variant in normalized_variants:
            if variant in state["files"]:
                try:
                    file_content = file_data_to_string(state["files"][variant])
                    return file_content
                except Exception:
                    continue

    # Try 2: Use local filesystem
    path = Path(normalized_path)
    if not path.exists():
        return f"Error: File '{file_path}' not found"

    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file '{file_path}': {e}"


def write_file_impl(
        file_path: str,
        content: str,
        state: Annotated[dict, InjectedState] = None
) -> str:
    """Write content to a file with virtual filesystem support.

    Writes content to the specified file path. If using a DeepAgents backend,
    the file is stored in the virtual filesystem. Otherwise, it writes to the
    local filesystem.

    Args:
        file_path: The path where the file should be written.
        content: The content to write to the file.
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        Confirmation message with the normalized file path, or an error message.
    """
    try:
        # Normalize the file path
        normalized_path = normalize_path_for_filesystem_tools(file_path)

        # Try to use virtual filesystem if available in state
        if state is not None:
            try:
                files = state.get("files", {})
                files[file_path] = create_file_data(content)
                state["files"] = files
                return f"Successfully wrote {len(content)} bytes to `{file_path}`"
            except Exception:
                pass

        # Fallback to local filesystem
        reports_output_folder = os.environ.get("OUTPUT_FOLDER", "./output")
        output_dir = Path(reports_output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Resolve the full path
        full_path = Path(normalized_path)
        if not full_path.is_absolute():
            full_path = output_dir / normalized_path

        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        full_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to `{normalize_path_for_filesystem_tools(str(full_path))}`"
    except Exception as e:
        return f"Error writing file `{file_path}`: {str(e)}"


def read_doc_folder_impl(
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
        logger.error(
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
            logger.info(f"Skipping {file_path.name}, already extracted to {target_path}")
            try:
                content = target_path.read_text(encoding="utf-8")
                processed_files.append(f"{file_path.name} (skipped, loaded from {target_path})")
                extracted_text.append(f"--- Content of {file_path.name} (from cache) ---\n{content}\n")
                continue
            except Exception as exc:
                logger.error(f"Failed to read existing extract {target_path}: {exc}. Re-extracting...")

        logger.info(f"Processing document: {file_path.name}...")
        try:
            content = extract_supported_document(file_path)
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

    total_text = "\n".join(extracted_text)
    if len(total_text) > 40000:
        logger.info("\n".join(summary_lines))
        return "\n".join(summary_lines + ["",
                                          f"Text omitted because total size is {len(total_text)} chars (too large to display inline). Please use the `read_file` tool on the specific file paths listed above to read them."])
    else:
        logger.info("\n".join(summary_lines))
        return "\n".join(summary_lines + ["", "--- EXTRACTED DOCUMENTS ---", ""] + extracted_text)
