from pathlib import Path


def test_agent_registers_trigger_dataset_evaluation_tool() -> None:
    agent_source = Path("agent.py").read_text(encoding="utf-8")

    assert "trigger_dataset_evaluation" in agent_source
    assert "tools=[" in agent_source


def test_agent_registers_frontend_slides_tool() -> None:
    agent_source = Path("agent.py").read_text(encoding="utf-8")

    assert "frontend_slides" in agent_source
    assert "tools=[" in agent_source
