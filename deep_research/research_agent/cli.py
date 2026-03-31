"""CLI helpers for the deep research entrypoint."""

from __future__ import annotations

import argparse
import os

from research_agent.targets import get_target_definition, list_target_ids

TARGET_SLIDES = "slides"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the research agent."""
    parser = argparse.ArgumentParser(
        description="Run the Deep Research Agent",
        add_help=False,
    )
    parser.add_argument(
        "subject",
        type=str,
        nargs="?",
        default="",
        help="Research subject. If omitted, a subject file may be used instead.",
    )
    parser.add_argument(
        "--subject-file",
        type=str,
        help="Optional file path to read the research subject from",
    )
    parser.add_argument(
        "--verify_ssl",
        default="True",
        nargs="?",
        const="True",
        help=(
            "Verify SSL certificates (default: True). "
            "Set to False to skip SSL verification"
        ),
    )
    parser.add_argument(
        "--ssl-ca-files",
        type=str,
        help="Path to a PEN CA buddle to use for HTTPS verification",
    )
    parser.add_argument(
        "--verbose",
        default="True",
        nargs="?",
        const="True",
        help="Show progress (default: True). When False, runs agent without progress display",
    )
    parser.add_argument(
        "--help",
        "-h",
        action="store_true",
        help="Show this help message and exit",
    )
    parser.add_argument(
        "--doc-folder",
        type=str,
        help="Optional folder containing supported documents to use as research material",
    )
    parser.add_argument(
        "--target",
        choices=list_target_ids(),
        help="Optional structured output target",
    )
    parser.add_argument(
        "--slides",
        action="store_true",
        help="Deprecated alias for `--target slides`",
    )
    parser.add_argument("--title", type=str, help="Optional research title for output file")
    return parser


def normalize_target(target: str | None, slides_flag: bool) -> str | None:
    """Normalize CLI target selection, honoring the legacy slides flag."""
    if target:
        return target
    if slides_flag:
        return TARGET_SLIDES
    return None


def build_instruction(
        subject: str,
        doc_folder: str | None = None,
        target: str | None = None,
        subject_file: str | None = None,
) -> str:
    """Build the user instruction sent to the agent."""
    if not subject and subject_file and os.path.exists(subject_file):
        with open(subject_file, "r", encoding="utf-8") as handle:
            subject = handle.read().strip()

    instruction = f"Research the following subject: {subject}"

    if not subject:
        instruction = "Research the application of artificial intelligence in healthcare"
    elif subject_file and os.path.exists(subject_file):
        instruction += f"\n\nNote: The subject was read from the file: {subject_file}"

    if doc_folder:
        instruction += (
            "\n\nPlease use the 'read_doc_folder' tool to read supported documents "
            f"from this folder first: '{doc_folder}'. Ground your answer in those docs "
            "when they are relevant."
        )

    if target:
        definition = get_target_definition(target)
        instruction += (
            f"\n\nThe requested output target is `{target}`."
            f"\nDescription: {definition['description']}"
            f"\nInstructions:\n{definition['instructions']}"
            "\nAfter researching, please call `render_target_output` with the selected "
            "target id and a JSON payload that matches that target schema exactly."
        )

    return instruction
