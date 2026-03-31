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


def _parse_skill_file(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(f"Skill file {path} is missing YAML frontmatter.")

    frontmatter = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    json_match = _JSON_BLOCK_RE.search(body)
    if not json_match:
        raise ValueError(f"Skill file {path} is missing a JSON schema block.")

    schema = json.loads(json_match.group(1))
    instructions = body[:json_match.start()].strip()
    render_template = frontmatter.get("render_template")
    if not render_template:
        raise ValueError(f"Skill file {path} is missing `render_template` in frontmatter.")

    target_id = frontmatter.get("name") or path.parent.name
    return {
        "id": target_id,
        "title": frontmatter.get("title", target_id.replace("-", " ").title()),
        "description": frontmatter.get("description", "").strip(),
        "instructions": instructions,
        "schema": schema,
        "render": {"template": render_template},
        "skill_path": str(path),
    }


@lru_cache(maxsize=1)
def _load_all_targets() -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for skill_path in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        definition = _parse_skill_file(skill_path)
        targets[definition["id"]] = definition
    return targets


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
