#!/usr/bin/env python3
"""
Script to replace all registries in uv.lock with the npm registry URL
resolved from `npm config list`.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path


def get_npm_registry() -> str:
    """
    Retrieve the npm registry URL by running `npm config list`.

    Returns the value of the `registry` key, or raises RuntimeError if it
    cannot be determined.
    """
    # Try different npm executable names for cross-platform compatibility
    for cmd_name in ["npm", "npm.cmd", "npm.exe"]:
        npm_cmd = shutil.which(cmd_name)
        if npm_cmd:
            break

    command: list[str]
    if npm_cmd:
        command = [npm_cmd, "config", "list"]
    elif sys.platform == "win32":
        # In some Windows venv sessions, npm is not directly resolvable but
        # node is; use npm-cli.js as a fallback.
        node_cmd = shutil.which("node")
        if node_cmd:
            npm_cli = (
                    Path(node_cmd).resolve().parent
                    / "node_modules"
                    / "npm"
                    / "bin"
                    / "npm-cli.js"
            )
            if npm_cli.exists():
                command = [node_cmd, str(npm_cli), "config", "list"]
            else:
                raise RuntimeError(
                    "npm is not installed or not on PATH. "
                    "Install Node.js/npm or pass --registry explicitly."
                )
        else:
            raise RuntimeError(
                "npm is not installed or not on PATH. "
                "Install Node.js/npm or pass --registry explicitly."
            )
    else:
        raise RuntimeError(
            "npm is not installed or not on PATH. "
            "Install Node.js/npm or pass --registry explicitly."
        )

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"npm config list failed: {exc.stderr.strip()}") from exc

    for line in result.stdout.splitlines():
        # Lines look like:  registry = "https://…/"  or  ; registry = "…" (comment)
        stripped = line.strip()
        if stripped.startswith(";"):
            continue
        match = re.match(r'^registry\s*=\s*"?([^"\s]+)"?', stripped)
        if match:
            return match.group(1).rstrip("/") + "/"

    raise RuntimeError(
        "Could not find 'registry' in `npm config list` output. "
        "Use --registry to supply it explicitly."
    )


def replace_registries_in_uv_lock(
        file_path: str, backup: bool = True, registry: str | None = None
) -> None:
    """
    Replace all registry URLs in uv.lock with the resolved npm registry URL.

    Args:
        file_path: Path to the uv.lock file
        backup: If True, creates a backup of the original file
        registry: Registry URL to use; resolved via `npm config list` when None
    """
    if registry is None:
        registry = get_npm_registry()
        print(f"Resolved registry from npm config: {registry}")

    file_path_obj = Path(file_path)
    if not file_path_obj.exists():
        print(f"Error: File not found: {file_path_obj}")
        sys.exit(1)

    # Read the file
    content = file_path_obj.read_text()
    original_content = content

    # Count matches before replacement
    matches = re.findall(r'registry = "([^"]*)"', content)
    print(f"Found {len(matches)} registry entries:")
    for i, match in enumerate(set(matches), 1):
        print(f"  {i}. {match}")

    # Create backup if requested
    if backup:
        backup_path = file_path_obj.with_suffix(file_path_obj.suffix + ".bak")
        backup_path.write_text(original_content)
        print(f"\nBackup created: {backup_path}")

    # Replace all registry URLs
    new_content = re.sub(
        r'registry = "[^"]*"',
        f'registry = "{registry}"',
        content,
    )

    # Count changes
    changes = sum(
        1
        for a, b in zip(original_content.split("\n"), new_content.split("\n"))
        if a != b
    )

    # Write the file
    file_path_obj.write_text(new_content)
    print(f"\nSuccessfully replaced registries in: {file_path_obj}")
    print(f"Lines modified: {changes}")
    print(f"New registry URL: {registry}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Replace registries in uv.lock with the npm registry URL"
    )
    parser.add_argument(
        "file_path",
        nargs="?",
        default="uv.lock",
        help="Path to the uv.lock file (default: uv.lock in current directory)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create a backup of the original file",
    )
    parser.add_argument(
        "--registry",
        default=None,
        help="Registry URL to use (default: resolved via `npm config list`)",
    )

    args = parser.parse_args()
    try:
        replace_registries_in_uv_lock(
            args.file_path, backup=not args.no_backup, registry=args.registry
        )
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
