"""
Golden dataset evaluation helpers.

Use `Evaluation process` in https://github.com/microsoft/promptflow-resource-hub/blob/main/sample_gallery/golden_dataset/copilot-golden-dataset-creation-guidance.md.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from model_factory import get_configured_model

load_dotenv()

METRIC_NAMES = ("Similarity", "Relevance", "Coherence", "Groundedness")
REQUIRED_INPUT_COLUMNS = ("Question", "Answer")
METRIC_GUIDANCE = {
    "Similarity": (
        "Measures how similar the response is to a human expert answer. "
        "Score on a scale of 1 to 5, where 1 is worst and 5 is best. "
        "Suggested goal: 3+."
    ),
    "Relevance": (
        "Measures how relevant the response is to the question and context provided. "
        "Score on a scale of 0 to 100. "
        "0-20 means the answer completely lacks confidence, 20-40 mostly lacks confidence, "
        "40-60 is partially confident, 60-80 is mostly confident, and 80-100 has perfect confidence. "
        "Suggested goal: 60+."
    ),
    "Coherence": (
        "Measures the quality of all sentences and how naturally they fit together. "
        "Score on a scale of 1 to 5, where 1 is worst and 5 is best. "
        "Suggested goal: 3+."
    ),
    "Groundedness": (
        "Measures how grounded the answer is against the provided context. "
        "Even if an answer seems true, it should score lower when it is not verifiable from context. "
        "Score on a scale of 1 to 5, where 1 is worst and 5 is best. "
        "Suggested goal: 3+."
    ),
}


def parse_metric_scores(response_text: str) -> dict[str, float]:
    """Extract metric values from judge output."""
    metrics: dict[str, float] = {}
    for metric_name in METRIC_NAMES:
        pattern = rf"{metric_name}\s*:\s*(-?\d+(?:\.\d+)?)"
        match = re.search(pattern, response_text, re.IGNORECASE)
        if not match:
            raise ValueError(f"Missing metric '{metric_name}' in judge response: {response_text}")
        metrics[metric_name] = float(match.group(1))
    return metrics


def build_judge_prompt(question: str, answer: str, context: str = "") -> str:
    """Create a deterministic judge prompt for the four dataset metrics."""
    context_block = context.strip() or "No grounding context was provided."
    metric_guidance_lines = "\n".join(
        f"- {metric_name}: {METRIC_GUIDANCE[metric_name]}" for metric_name in METRIC_NAMES
    )
    return (
        "You are evaluating a draft golden_dataset answer for QA purposes.\n"
        "Score the answer on four metrics and return exactly these four lines:\n"
        "Similarity: <1-5 score>\n"
        "Relevance: <0-100 score>\n"
        "Coherence: <1-5 score>\n"
        "Groundedness: <1-5 score>\n\n"
        "Use these metric descriptions and suggested goals as best practice:\n"
        f"{metric_guidance_lines}\n"
        "Return numbers only, with no extra commentary.\n\n"
        f"Question:\n{question.strip()}\n\n"
        f"Draft Answer:\n{answer.strip()}\n\n"
        f"Context:\n{context_block}\n"
    )


def score_row(model, row: dict[str, str]) -> dict[str, float]:
    """Evaluate one dataset row with the configured judge model."""
    prompt = build_judge_prompt(
        question=row["Question"],
        answer=row["Answer"],
        context=row.get("Context", ""),
    )
    response = model.invoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "\n".join(str(part) for part in content)
    return parse_metric_scores(str(content))


def validate_input_columns(fieldnames: Iterable[str] | None) -> None:
    """Validate that the input dataset contains the expected minimum columns."""
    existing = set(fieldnames or [])
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in existing]
    if missing:
        raise ValueError(
            "Input dataset is missing required columns: " + ", ".join(missing)
        )


def score_dataset_file(input_csv: str, output_csv: str) -> Path:
    """Read a dataset CSV, append quality metrics, and write the enriched file."""
    input_path = Path(input_csv)
    output_path = Path(output_csv)

    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        validate_input_columns(reader.fieldnames)
        rows = list(reader)
        base_fieldnames = list(reader.fieldnames or [])

    model = get_configured_model()
    scored_rows: list[dict[str, str]] = []
    for row in rows:
        metrics = score_row(model, row)
        enriched_row = dict(row)
        for metric_name, metric_value in metrics.items():
            enriched_row[metric_name] = (
                str(int(metric_value)) if float(metric_value).is_integer() else str(metric_value)
            )
        scored_rows.append(enriched_row)

    fieldnames = base_fieldnames + [name for name in METRIC_NAMES if name not in base_fieldnames]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scored_rows)

    return output_path


def metrics_to_json(scores: dict[str, float]) -> str:
    """Serialize metrics for logging or downstream tooling."""
    return json.dumps(scores, sort_keys=True)
