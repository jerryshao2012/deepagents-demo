"""CLI helpers for the deep research entrypoint."""

from __future__ import annotations

import argparse
import os

from research_agent.utils.skill_registry import get_skill_registry


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
        "--no-web",
        action="store_true",
        help="Disable web search (Tavily) during research",
    )
    # Collect both legacy (SkillRegistry) and migrated (SkillsMiddleware) skill IDs
    _all_skill_ids = get_skill_registry().list_skill_ids() + list(
        get_skill_registry().SKILL_IDS
    )
    parser.add_argument(
        "--skill",
        choices=["list", *_all_skill_ids],
        help="Optional structured output skill. Use '--skill list' to see all options.",
    )
    parser.add_argument("--title", type=str, help="Optional research title for output file")
    parser.add_argument(
        "--eval-golden-dataset",
        action="store_true",
        help="Enable golden-dataset regression tracking and JSONL report output.",
    )
    parser.add_argument(
        "--eval-mode",
        choices=["baseline", "candidate"],
        default="candidate",
        help="Evaluation mode for --eval-golden-dataset (default: candidate).",
    )
    parser.add_argument(
        "--eval-history-file",
        type=str,
        help=(
            "Optional JSONL output file path for evaluation history. "
            "Default: ./output/eval_history/golden_dataset_runs.jsonl"
        ),
    )
    return parser


def list_skills() -> None:
    """Print available research skills to console."""
    catalog = get_skill_registry().format_skill_catalog()
    print("\nAvailable research skills:")
    print(catalog)
    print("\nUse --skill <id> to select one.")


def build_instruction(
        subject: str,
        doc_folder: str | None = None,
        skill: str | None = None,
        subject_file: str | None = None,
        no_web: bool = False,
) -> str:
    """Build the user instruction sent to the agent."""
    if not subject and subject_file and os.path.exists(subject_file):
        with open(subject_file, "r", encoding="utf-8") as handle:
            subject = handle.read().strip()

    instruction = f"Research the following subject: {subject}"

    if doc_folder:
        instruction += (
            "\n\nPlease use the 'read_doc_folder' tool to read supported documents "
            f"from this folder first: '{doc_folder}'. Ground your answer in those docs "
            "when they are relevant."
        )

    if no_web:
        instruction += (
            "\n\n**CRITICAL: Do NOT use web search for this research task.** "
            "Use only provided documentation or your internal knowledge."
        )

    if skill:
        # Check if this skill has been migrated to the deep agents SkillsMiddleware
        if skill in get_skill_registry().SKILL_IDS:
            instruction += (
                f"\n\nThe requested output skill is `{skill}`. "
                f"This skill is available in the Skills library. "
                f"Use `read_file` to load the skill's SKILL.md for full instructions "
                f"and follow its workflow precisely. "
                f"Save your final output using `write_file` to `/final_report.md`."
            )
        else:
            definition = get_skill_registry().get_skill_definition(skill)
            instruction += (
                f"\n\nThe requested output skill is `{skill}`."
                f"\nDescription: {definition['description']}"
                f"\nInstructions:\n{definition['instructions']}"
            )
            if definition.get("schema"):
                instruction += (
                    "\nAfter researching, please call `render_skill_output` with the selected "
                    "skill id and a JSON payload that matches that skill schema exactly."
                )
            else:
                instruction += (
                    "\nFollow the skill instructions above precisely. "
                    "Use the `write_file` tool to save your output to `/final_report.md`. "
                    "Do NOT use `render_skill_output` since this is an unstructured skill. "
                    "Do NOT just say you will write it; you must actually call the `write_file` tool with the text."
                )
        if skill == "golden-dataset":
            instruction += (
                "\n\n**Golden dataset delivery — MANDATORY tool-call sequence (zero exceptions):**\n"
                "After you have read the documents and drafted all items, you MUST execute these "
                "tool calls in this exact order — do NOT write any description of your plan, do NOT "
                "ask for confirmation, and do NOT stop after a verbal summary:\n"
                "  1. Call `render_skill_output` with skill_id='golden-dataset' and the full JSON payload.\n"
                "  2. Immediately call `finalize_golden_dataset_output` with the IDENTICAL JSON string. "
                "This is what writes the CSV to disk — skipping it means no file is saved.\n"
                "  3. Only after both tool calls succeed, write a short confirmation summary.\n"
                "WARNING: Any response that says 'I will synthesize', 'Next I will call...', or "
                "'Please stand by' without those tool calls already having been executed is wrong."
            )

    return instruction
