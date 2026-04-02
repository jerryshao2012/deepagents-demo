"""Target definition loading from skill folders."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_JSON_BLOCK_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
_SCHEMA_SECTION_RE = re.compile(r"^## Schema\s*$", re.MULTILINE)
_RENDER_SPEC_SECTION_RE = re.compile(r"^## Render Spec\s*$", re.MULTILINE)
_QUALITY_GUIDELINES_SECTION_RE = re.compile(r"^## Quality Guidelines\s*$", re.MULTILINE)
SUPPORTED_RENDER_TEMPLATES = {"markdown_blocks"}


def _extract_schema_block(body: str, path: Path) -> tuple[str, dict[str, Any]]:
    schema_heading = _SCHEMA_SECTION_RE.search(body)
    if not schema_heading:
        raise ValueError(f"Skill file {path} is missing a `## Schema` section.")

    schema_body = body[schema_heading.end():]
    json_match = _JSON_BLOCK_RE.search(schema_body)
    if not json_match:
        raise ValueError(f"Skill file {path} is missing a JSON schema block in `## Schema`.")

    schema = json.loads(json_match.group(1))
    instructions = body[:schema_heading.start()].strip()
    return instructions, schema


def _extract_render_spec(body: str, path: Path) -> list[dict[str, Any]]:
    render_heading = _RENDER_SPEC_SECTION_RE.search(body)
    if not render_heading:
        raise ValueError(f"Skill file {path} is missing a `## Render Spec` section.")

    render_body = body[render_heading.end():]
    json_match = _JSON_BLOCK_RE.search(render_body)
    if not json_match:
        raise ValueError(
            f"Skill file {path} is missing a JSON render spec block in `## Render Spec`."
        )

    render_spec = json.loads(json_match.group(1))
    if not isinstance(render_spec, list):
        raise ValueError(f"Skill file {path} render spec must be a JSON array.")
    return render_spec


def _extract_quality_guidelines(body: str) -> str:
    """Extract the raw Markdown text of the ## Quality Guidelines section, or empty string."""
    guidelines_heading = _QUALITY_GUIDELINES_SECTION_RE.search(body)
    if not guidelines_heading:
        return ""
    # Grab everything from after the heading to the next ## section (or end of file)
    start = guidelines_heading.end()
    next_section = re.search(r"^## ", body[start:], re.MULTILINE)
    end = (start + next_section.start()) if next_section else len(body)
    return body[start:end].strip()


def _parse_skill_file(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(f"Skill file {path} is missing YAML frontmatter.")

    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    instructions, schema = _extract_schema_block(body, path)
    render_spec = _extract_render_spec(body, path)
    render_template = frontmatter.get("render_template")
    if not render_template:
        raise ValueError(f"Skill file {path} is missing `render_template` in frontmatter.")
    if render_template not in SUPPORTED_RENDER_TEMPLATES:
        supported = ", ".join(sorted(SUPPORTED_RENDER_TEMPLATES))
        raise ValueError(
            f"Skill file {path} uses unsupported render_template '{render_template}'. "
            f"Supported templates: {supported}."
        )

    target_id = frontmatter.get("name") or path.parent.name
    targets = {
        target_id: {
            "id": target_id,
            "title": frontmatter.get("title", target_id.replace("-", " ").title()),
            "description": frontmatter.get("description", "").strip(),
            "instructions": instructions,
            "quality_guidelines": _extract_quality_guidelines(body),
            "schema": schema,
            "render": {"template": render_template, "spec": render_spec},
            "skill_path": str(path),
        }
    }

    return targets


@lru_cache(maxsize=1)
def _load_all_targets() -> dict[str, dict[str, Any]]:
    all_targets: dict[str, dict[str, Any]] = {}
    for skill_path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill_targets = _parse_skill_file(skill_path)
        all_targets.update(skill_targets)
    return all_targets


def list_target_ids() -> list[str]:
    """List available target ids."""
    return sorted(_load_all_targets().keys())


def get_target_definition(target_id: str) -> dict[str, Any]:
    """Get one target definition by id."""
    try:
        return _load_all_targets()[target_id]
    except KeyError as exc:
        available = ", ".join(list_target_ids()) or "(none)"
        raise ValueError(
            f"Unknown target '{target_id}'. Available targets: {available}."
        ) from exc


def format_target_catalog() -> str:
    """Format a short target catalog for prompt text."""
    lines = []
    for target_id in list_target_ids():
        definition = get_target_definition(target_id)
        lines.append(
            f"- `{target_id}`: {definition['title']} — {definition['description']}"
        )
    return "\n".join(lines)


def format_target_quality_guidelines() -> str:
    """Aggregate Quality Guidelines from all skill SKILL.md files into a prompt block.

    Only includes skills that have a ## Quality Guidelines section. Each skill's
    guidelines are prefaced with the skill name so the LLM knows which target they apply to.
    """
    blocks: list[str] = []
    for target_id in list_target_ids():
        definition = get_target_definition(target_id)
        guidelines = definition.get("quality_guidelines", "").strip()
        if guidelines:
            blocks.append(f"### `{target_id}` Quality Guidelines\n\n{guidelines}")
    if not blocks:
        return ""
    return "\n\n".join(blocks)
