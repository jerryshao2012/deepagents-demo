from research_agent.utils.cli import build_parser
from research_agent.utils.skill_registry import get_skill_registry

# After migration, only golden-dataset remains in the legacy SkillRegistry.
# All other skills (including frontend-slides) are loaded by SkillsMiddleware
# from .deepagents/skills/.

ALL_SKILL_TARGET_IDS = {
    "golden-dataset",
}

STRUCTURED_TARGET_IDS = {
    "golden-dataset",
}

UNSTRUCTURED_TARGET_IDS = ALL_SKILL_TARGET_IDS - STRUCTURED_TARGET_IDS  # empty


def test_all_skill_skills_are_discoverable() -> None:
    assert set(get_skill_registry().list_skill_ids()) == ALL_SKILL_TARGET_IDS


def test_parser_exposes_all_skill_skills() -> None:
    parser = build_parser()
    # Parser choices include both legacy + migrated skill IDs + "list"
    expected = ALL_SKILL_TARGET_IDS | {"list"}
    for sid in get_skill_registry().MIGRATED_SKILL_IDS:
        expected.add(sid)
    assert set(parser._option_string_actions["--skill"].choices) == expected


def test_structured_and_unstructured_skill_classification() -> None:
    for skill_id in STRUCTURED_TARGET_IDS:
        definition = get_skill_registry().get_skill_definition(skill_id)
        assert definition["schema"] is not None
        assert definition["render"] is not None

    # No unstructured legacy skills remain after frontend-slides migration
    for skill_id in UNSTRUCTURED_TARGET_IDS:
        definition = get_skill_registry().get_skill_definition(skill_id)
        assert definition["schema"] is None
        assert definition["render"] is None


def test_golden_dataset_skill_contract_mentions_required_export_sequence() -> None:
    definition = get_skill_registry().get_skill_definition("golden-dataset")
    instructions = definition["instructions"]
    guidelines = definition["quality_guidelines"]

    assert "COMPLETION SEQUENCE" in instructions
    assert "finalize_golden_dataset_output" in instructions
    assert "Item count" in guidelines
    assert "Metric readiness" in guidelines


def test_skills_middleware_loads_migrated_skills() -> None:
    """Verify all 8 migrated skills exist in .deepagents/skills/."""
    from pathlib import Path

    skills_dir = Path(__file__).resolve().parent.parent / ".deepagents" / "skills"
    migrated_dirs = {
        d.name
        for d in skills_dir.iterdir()
        if d.is_dir()
    }

    expected = {
        "autoresearch-universal",
        "code-generator",
        "find-skills",
        "frontend-slides",
        "humanizer",
        "interview",
        "interview-coach-pro",
        "study-slides",
    }
    assert migrated_dirs == expected
