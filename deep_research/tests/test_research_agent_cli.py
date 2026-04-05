from research_agent import targets
from research_agent.cli import build_instruction, build_parser
from research_agent.targets import get_target_definition, list_target_ids


def test_parser_accepts_doc_folder_and_target() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["Research AI Agents", "--doc-folder", "./docs", "--target", "study-slides"]
    )

    assert args.subject == "Research AI Agents"
    assert args.doc_folder == "./docs"
    assert args.target == "study-slides"


def test_parser_uses_discovered_targets() -> None:
    parser = build_parser()

    assert set(parser._option_string_actions["--target"].choices) == set(list_target_ids()) | {"list"}


def test_build_instruction_for_slides_target() -> None:
    instruction = build_instruction(
        "AI Agents", doc_folder="./docs", target="study-slides"
    )

    assert "Research the following subject: AI Agents" in instruction
    assert "read_doc_folder" in instruction
    assert "'./docs'" in instruction
    assert "render_target_output" in instruction
    assert "fewer than 5 slides" in instruction


def test_build_instruction_for_interview_target() -> None:
    instruction = build_instruction(
        "AI Agents", doc_folder="./docs", target="interview"
    )

    assert "read_doc_folder" in instruction
    assert "render_target_output" in instruction
    assert "45-minute interview" in instruction


def test_build_instruction_for_golden_dataset_target() -> None:
    instruction = build_instruction(
        "HR policies", doc_folder="./docs", target="golden-dataset"
    )

    assert "golden-dataset" in instruction
    assert "render_target_output" in instruction
    assert "finalize_golden_dataset_output" in instruction


def test_target_definition_is_loaded_from_skill() -> None:
    definition = get_target_definition("study-slides")

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

    monkeypatch.setattr(targets, "SKILLS_DIR", tmp_path / "skills")
    targets._load_all_targets.cache_clear()
    try:
        definition = targets.get_target_definition("demo")
    finally:
        targets._load_all_targets.cache_clear()

    assert definition["schema"]["required"] == ["topic"]
    assert definition["render"]["spec"][0]["type"] == "heading"
