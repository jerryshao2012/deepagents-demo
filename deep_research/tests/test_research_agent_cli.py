from research_agent.cli import build_instruction, build_parser
from research_agent.targets import get_target_definition, list_target_ids


def test_parser_accepts_doc_folder_and_target() -> None:
    parser = build_parser()

    args = parser.parse_args(
        ["Research AI Agents", "--doc-folder", "./docs", "--target", "slides"]
    )

    assert args.subject == "Research AI Agents"
    assert args.doc_folder == "./docs"
    assert args.target == "slides"


def test_parser_uses_discovered_targets() -> None:
    parser = build_parser()

    assert set(parser._option_string_actions["--target"].choices) == set(list_target_ids())


def test_build_instruction_for_slides_target() -> None:
    instruction = build_instruction(
        "AI Agents", doc_folder="./docs", target="slides"
    )

    assert "Research the following subject: AI Agents" in instruction
    assert "read_doc_folder" in instruction
    assert "'./docs'" in instruction
    assert "render_target_output" in instruction
    assert "fewer than 3 slides" in instruction


def test_build_instruction_for_interview_target() -> None:
    instruction = build_instruction(
        "AI Agents", doc_folder="./docs", target="interview"
    )

    assert "read_doc_folder" in instruction
    assert "render_target_output" in instruction
    assert "45-minute interview" in instruction


def test_target_definition_is_loaded_from_skill() -> None:
    definition = get_target_definition("slides")

    assert definition["id"] == "slides"
    assert "schema" in definition
    assert "render" in definition
    assert "skill_path" in definition
