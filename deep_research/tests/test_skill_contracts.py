from research_agent.cli import build_parser
from research_agent.targets import get_target_definition, list_target_ids

ALL_SKILL_TARGET_IDS = {
    "autoresearch-universal",
    "code-generator",
    "golden-dataset",
    "interview",
    "interview-coach-pro",
    "study-slides",
}

STRUCTURED_TARGET_IDS = {
    "golden-dataset",
    "interview",
    "study-slides",
}

UNSTRUCTURED_TARGET_IDS = ALL_SKILL_TARGET_IDS - STRUCTURED_TARGET_IDS


def test_all_skill_targets_are_discoverable() -> None:
    assert set(list_target_ids()) == ALL_SKILL_TARGET_IDS


def test_parser_exposes_all_skill_targets() -> None:
    parser = build_parser()

    assert set(parser._option_string_actions["--target"].choices) == ALL_SKILL_TARGET_IDS | {"list"}


def test_structured_and_unstructured_skill_classification() -> None:
    for target_id in STRUCTURED_TARGET_IDS:
        definition = get_target_definition(target_id)
        assert definition["schema"] is not None
        assert definition["render"] is not None

    for target_id in UNSTRUCTURED_TARGET_IDS:
        definition = get_target_definition(target_id)
        assert definition["schema"] is None
        assert definition["render"] is None


def test_study_slides_skill_contract_mentions_slide_output_requirements() -> None:
    definition = get_target_definition("study-slides")
    instructions = definition["instructions"]
    guidelines = definition["quality_guidelines"]

    assert "fewer than 5 slides" in definition["description"]
    assert "Include speaking notes for each slide" in instructions
    assert "Slide count" in guidelines
    assert "Speaker notes depth" in guidelines


def test_interview_skill_contract_mentions_45_minute_structure() -> None:
    definition = get_target_definition("interview")
    instructions = definition["instructions"]
    guidelines = definition["quality_guidelines"]

    assert "45-minute interview kit" in definition["title"].lower() or "45-minute interview" in instructions
    assert "Produce exactly 8 agenda items" in instructions
    assert "Total time" in guidelines
    assert "Difficulty progression" in guidelines


def test_golden_dataset_skill_contract_mentions_required_export_sequence() -> None:
    definition = get_target_definition("golden-dataset")
    instructions = definition["instructions"]
    guidelines = definition["quality_guidelines"]

    assert "COMPLETION SEQUENCE" in instructions
    assert "Call `render_target_output`" in instructions
    assert "Call `finalize_golden_dataset_output`" in instructions
    assert "Item count" in guidelines
    assert "Metric readiness" in guidelines


def test_code_generator_skill_contract_mentions_code_block_output() -> None:
    definition = get_target_definition("code-generator")
    body = definition["instructions"] + "\n" + definition["quality_guidelines"]

    assert "markdown code block" in body.lower() or "fenced code blocks" in body.lower()
    assert "self-contained" in body.lower()
    assert "setup or installation" in body.lower()


def test_interview_coach_pro_skill_contract_mentions_star_answers_and_markdown_table() -> None:
    definition = get_target_definition("interview-coach-pro")
    instructions = definition["instructions"]

    assert "markdown table" in instructions.lower()
    assert "STAR-format answers" in instructions
    assert "STAR is a framework for ANSWERS only" in instructions
    assert "Total questions: 5–7" in instructions or "Total questions: 5-7" in instructions


def test_autoresearch_universal_skill_contract_mentions_plan_mode_and_phases() -> None:
    definition = get_target_definition("autoresearch-universal")
    instructions = definition["instructions"]

    assert "switch to Plan mode" in instructions
    assert "Phase 1" in instructions
    assert "Phase 2" in instructions
    assert "Phase 3" in instructions
    assert "Phase 4" in instructions
    assert "Phase 5" in instructions
