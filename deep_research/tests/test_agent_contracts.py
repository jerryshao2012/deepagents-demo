from pathlib import Path


def test_agent_registers_frontend_slides_tool() -> None:
    agent_source = Path("agent.py").read_text(encoding="utf-8")

    assert "frontend_slides" in agent_source
    assert "tools=[" in agent_source
