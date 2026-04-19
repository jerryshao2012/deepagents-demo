from research_agent import skill_registry
from research_agent.cli import build_parser
from research_agent.skill_registry import get_skill_registry


def test_parser_accepts_doc_folder_and_target() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["Research AI Agents", "--doc-folder", "./docs", "--target", "study-slides"]
    )

    assert args.subject == "Research AI Agents"
    assert args.doc_folder == "./docs"
    assert args.target == "study-slides"


def test_skill_definition_is_loaded_from_skill() -> None:
    definition = get_skill_registry().get_skill_definition("study-slides")

    assert definition["id"] == "study-slides"
    assert "schema" in definition
    assert "render" in definition
    assert "skill_path" in definition
    assert isinstance(definition["render"]["spec"], list)


def test_target_loader_uses_explicit_schema_section(tmp_path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        """---
name: demo
title: Demo Target
description: Demo target for testing
render_template: markdown_blocks
---

## Instructions

Here is an example payload:

```json
{"example": true}
```

## Schema

```json
{
  "type": "object",
  "required": ["topic"],
  "properties": {
    "topic": {"type": "string"}
  }
}
```

## Render Spec

```json
[
  {"type": "heading", "level": 1, "value": "Demo: {topic}"}
]
```
""",
        encoding="utf-8",
    )

    # We need to re-initialize the registry to read the new skill
    registry = skill_registry.SkillRegistry(tmp_path / "skills")
    monkeypatch.setattr(skill_registry, "get_skill_registry", lambda: registry)

    definition = skill_registry.get_skill_definition("demo")

    assert definition["schema"]["required"] == ["topic"]
    assert definition["render"]["spec"][0]["type"] == "heading"