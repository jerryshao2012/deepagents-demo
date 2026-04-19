from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from deepagents.backends.utils import file_data_to_string
from dotenv import load_dotenv
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

# Load environment variables
load_dotenv()
# These can be configured via environment variables with sensible defaults
MAX_GLOB_DEPTH = int(os.environ.get("MAX_GLOB_DEPTH", "3"))
REPORTS_OUTPUT_FOLDER = os.environ.get("REPORTS_OUTPUT_FOLDER", "./output")
MAX_FILES_TO_READ = int(os.environ.get("MAX_FILES_TO_READ", "20"))
MAX_TOTAL_SIZE_MB = int(os.environ.get("MAX_TOTAL_SIZE_MB", "50"))

SUPPORTED_DOC_SUFFIXES = {".pdf", ".txt", ".md", ".docx", ".pptx", ".xlsx"}

# Global in‑memory cache for folder listings (path → list of Path objects)
_folder_listing_cache: dict[str, list[Path]] = {}


def _normalize_path_for_filesystem_tools(path_str: str) -> str:
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


def _get_extracted_path(file_path: Path, output_folder: Path) -> Path:
    """Get the target path for an extracted file."""
    suffix = file_path.suffix.lower()
    if suffix in {".pdf", ".md", ".docx", ".pptx"}:
        new_extension = ".md"
    else:
        new_extension = ".txt"

    new_filename = f"{file_path.name}_extracted{new_extension}"
    return output_folder / "extracted" / new_filename


def _resolve_doc_output_subfolder(folder: Path) -> Path:
    configured_output = Path(os.environ.get("OUTPUT_FOLDER", REPORTS_OUTPUT_FOLDER))
    if configured_output.name == folder.name:
        return configured_output
    if configured_output == Path(REPORTS_OUTPUT_FOLDER):
        return configured_output / folder.name
    return configured_output


@tool(parse_docstring=True)
def ls(path: str, state: Annotated[dict, InjectedState] = None) -> str:
    """List files in a directory with fallback support.
    
    Tries to list from the virtual filesystem in state first (DeepAgents backend),
    then falls back to the local filesystem if not available.

    Args:
        path: The path to the directory to list.
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        A list of files in the directory or an error message.
    """
    normalized_path = _normalize_path_for_filesystem_tools(path)

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
    normalized_path = _normalize_path_for_filesystem_tools(path)
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


@tool(parse_docstring=True)
def glob(pattern: str, state: Annotated[dict, InjectedState] = None) -> str:
    """Find files matching a glob pattern with fallback support.
    
    Tries to match against the virtual filesystem in state first, then falls back
    to the local filesystem if not available.

    Args:
        pattern: The glob pattern to match (e.g., "**/*.md").
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        A list of matching file paths or an error message.
    """
    normalized_pattern = _normalize_path_for_filesystem_tools(pattern)

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
    normalized_pattern = _normalize_path_for_filesystem_tools(pattern)

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


@tool(parse_docstring=True)
def read_file(file_path: str,
              state: Annotated[dict, InjectedState] = None) -> str:
    """Read the content of a file with fallback support.
    
    Tries to read from the virtual filesystem in state first (DeepAgents backend),
    then falls back to the local filesystem if not available.

    Args:
        file_path: The path to the file to read.
        state: LangGraph state containing virtual filesystem (injected automatically).

    Returns:
        The content of the file or an error message if the file not found.
    """
    # Normalize path first for consistent comparison across both filesystems
    normalized_path = _normalize_path_for_filesystem_tools(file_path)

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
