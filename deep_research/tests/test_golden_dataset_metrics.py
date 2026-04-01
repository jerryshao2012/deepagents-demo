from research_agent.skills.golden_dataset.scripts.golden_dataset_metrics import (
    build_judge_prompt,
    parse_metric_scores,
)


def test_parse_metric_scores_extracts_expected_columns() -> None:
    scores = parse_metric_scores(
        """
        Similarity: 4.0
        Relevance: 81
        Coherence: 4
        Groundedness: 3.5
        """
    )

    assert scores == {
        "Similarity": 4.0,
        "Relevance": 81.0,
        "Coherence": 4.0,
        "Groundedness": 3.5,
    }


def test_parse_metric_scores_rejects_missing_metrics() -> None:
    try:
        parse_metric_scores(
            """
            Similarity: 4
            Relevance: 80
            Coherence: 4
            """
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ValueError for missing metric")

    assert "Groundedness" in message


def test_build_judge_prompt_includes_metric_descriptions_and_goals() -> None:
    prompt = build_judge_prompt(
        question="What is the parental leave policy?",
        answer="Employees should review the handbook and submit a request to HR.",
        context="The handbook explains leave policy and approval steps.",
    )

    assert "Measures how similar the response is to a human expert answer" in prompt
    assert "Suggested goal: 3+" in prompt
    assert "Suggested goal: 60+" in prompt
    assert "Measures the quality of all sentences" in prompt
    assert "Measures how grounded the answer is against the provided context" in prompt
