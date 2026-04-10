from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

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
def ls(path: str) -> str:
    """List files in a directory.

    Args:
        path: The path to the directory to list.

    Returns:
        A list of files in the directory or an error message.
    """
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
def glob(pattern: str) -> str:
    """Find files matching a glob pattern.

    Args:
        pattern: The glob pattern to match (e.g., "**/*.md").

    Returns:
        A list of matching file paths or an error message.
    """
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
def read_file(file_path: str) -> str:
    """Read the content of a file.

    Args:
        file_path: The path to the file to read.

    Returns:
        The content of the file or an error message if the file not found.
    """
    normalized_path = _normalize_path_for_filesystem_tools(file_path)
    path = Path(normalized_path)
    if not path.exists():
        return f"Error: File '{file_path}' not found"

    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file '{file_path}': {e}"
