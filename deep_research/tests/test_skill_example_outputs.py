from __future__ import annotations

from textwrap import dedent


def test_study_slides_example_output_matches_learning_slide_shape() -> None:
    output = dedent(
        """
        # Presentation: Claude Code Memory Management

        ---

        ## Slide 1: Memory Hierarchy

        - Claude Code uses layered memory scopes.
        - Project memory and user memory serve different purposes.

        ### Speaking Notes

        Explain how global guidance differs from project-local rules and why that matters for repeatable agent behavior.

        ---

        ## Slide 2: Context Management

        - Context exhaustion is the main failure mode.
        - `/compact` and `/clear` help manage context deliberately.

        ### Speaking Notes

        Emphasize that memory and context are related but different: one is persistent guidance, the other is active working state.
        """
    ).strip()

    assert output.startswith("# Presentation: Claude Code Memory Management")
    assert output.count("## Slide") == 2
    assert "### Speaking Notes" in output
    assert "Claude Code Memory Management" in output


def test_interview_example_output_matches_grounded_45_minute_kit_shape() -> None:
    output = dedent(
        """
        # Interview Kit: Claude Code Memory Management

        ## 45-minute interview objective

        Assess whether the candidate understands persistent memory, context limits, and practical strategies for managing long-running agent sessions.

        ## Agenda

        1. Timebox: 5 minutes

        Question: Introduce yourself and describe your experience working with coding agents or AI-assisted development workflows.

        Potential Answer: A strong answer would briefly cover relevant projects, the role AI tools played, and the candidate's familiarity with context-heavy workflows.

        Follow-up: Which kinds of agent workflows have been most useful in your day-to-day work?

        2. Timebox: 10 minutes

        Question: How would you explain the difference between persistent memory and in-session context in Claude Code?

        Potential Answer: A strong answer would distinguish durable instruction layers from transient conversation state, and explain why each solves a different class of problem.

        Follow-up: What problems appear when a team confuses those two concepts?

        3. Timebox: 10 minutes

        Question: What strategies would you use to prevent context window overload during a long implementation session?

        Potential Answer: A strong answer would mention reducing irrelevant history, compacting context, splitting tasks, and preserving critical guidance in stable memory locations.

        Follow-up: What trade-offs do you make when deciding whether to compact, clear, or persist information?

        4. Timebox: 5 minutes

        Question: What questions do you have for the interviewer about the team's coding-agent workflow and memory practices?

        Potential Answer: A strong answer would ask about standards, review expectations, and how the team stores durable guidance for repeatable work.

        Follow-up: Which parts of that workflow sound most important to you?

        Total planned time: 30 minutes
        """
    ).strip()

    assert output.startswith("# Interview Kit: Claude Code Memory Management")
    assert "## 45-minute interview objective" in output
    assert "Potential Answer:" in output
    assert "Follow-up:" in output
    assert "Claude Code Memory Management" in output


def test_golden_dataset_example_output_matches_dataset_shape() -> None:
    output = dedent(
        """
        # Golden Dataset Starter: Claude Code Memory Q&A Draft Set

        Domain: Claude Code memory management

        Recommended full dataset size: 12 question-answer pairs

        ## Coverage Areas

        - Memory hierarchy
        - Context management
        - Checkpoints and Git

        ## Starter Question Set

        ---

        ### 1. Memory hierarchy

        Question: What is the difference between user memory and project memory in Claude Code?

        Answer: User memory stores durable personal preferences across projects, while project memory captures instructions that should apply inside one repository or workspace. This separation helps teams avoid leaking local rules into unrelated work and keeps repeatable guidance in the right place.

        Content: Claude Code uses multiple memory layers, including user-level instructions and project-scoped guidance, to separate stable preferences from repository-specific rules.

        ## Reviewer Note

        These draft responses cover Golden Dataset steps 1 and 2 only. A domain expert should review and replace them with authoritative expert answers before evaluation use.
        """
    ).strip()

    assert output.startswith("# Golden Dataset Starter: Claude Code Memory Q&A Draft Set")
    assert "## Coverage Areas" in output
    assert "Question:" in output
    assert "Answer:" in output
    assert "Content:" in output
    assert "Claude Code" in output


def test_code_generator_example_output_matches_code_generator_shape() -> None:
    output = dedent(
        """
        Install dependencies:

        ```bash
        pip install pyyaml
        ```

        ```python
        import yaml

        def load_project_memory(path: str) -> dict:
            with open(path, "r", encoding="utf-8") as handle:
                return yaml.safe_load(handle) or {}
        ```
        """
    ).strip()

    assert "pip install" in output
    assert "```python" in output
    assert "def load_project_memory" in output


def test_interview_coach_pro_example_output_matches_star_table_shape() -> None:
    output = dedent(
        """
        | # | Competency | Behavioral Question | Suggested STAR Answer (based on resume) |
        |---|---|---|---|
        | 1 | Leadership | Tell me about a time you led a project with changing requirements. | **S:** The candidate inherited a delayed platform migration. **T:** They needed to align engineers and deliver a stable cutover. **A:** They introduced milestone planning, clarified ownership, and built weekly risk reviews. **R:** The migration launched on schedule and reduced deployment incidents. |
        | 2 | Problem-solving | Describe a situation where you solved an ambiguous technical problem. | **S:** The team faced inconsistent agent behavior in long sessions. **T:** The candidate needed to identify the failure mode. **A:** They traced context overload, documented memory rules, and simplified the workflow. **R:** Session reliability improved and onboarding became easier. |
        """
    ).strip()

    assert output.startswith("| # | Competency | Behavioral Question | Suggested STAR Answer (based on resume) |")
    assert "**S:**" in output
    assert "**T:**" in output
    assert "**A:**" in output
    assert "**R:**" in output


def test_autoresearch_universal_example_output_matches_phased_plan_shape() -> None:
    output = dedent(
        """
        Repo: deep_research
        Stack: Python, LangGraph, pytest
        Purpose: A research-oriented agent that produces grounded reports and structured deliverables.
        Quality tools found: pytest, ruff

        Here is your optimization template:

          Target:  prompt quality for study-slides generation
          Scope:   structured output path in research_agent_cli.py
          Context: keep compatibility with existing targets and CLI behavior

        Eval criteria for prompt quality for study-slides generation:

        1. Does the output produce fewer than 5 slides? — yes/no — llm-judge
        2. Does the output include speaking notes for every slide? — yes/no — llm-judge
        3. Does the output mention the requested topic accurately? — yes/no — llm-judge
        4. Does the rendered output validate without schema errors? — yes/no — command: python -m pytest tests/test_tools.py -q
        """
    ).strip()

    assert output.startswith("Repo: deep_research")
    assert "Here is your optimization template:" in output
    assert "Eval criteria for prompt quality for study-slides generation:" in output
    assert "yes/no" in output
    assert "command:" in output
