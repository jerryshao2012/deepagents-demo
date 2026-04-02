---
name: golden-dataset
title: Golden Dataset Starter
description: Produce a Golden Dataset starter pack with realistic customer questions and draft LLM answers only. Use for deep research outputs that should cover Golden Dataset steps 1 and 2, then score the exported CSV separately with the bundled quality-metrics script.
render_template: markdown_blocks
---

## Instructions

Create a Golden Dataset starter pack grounded in the available documents and research findings.

This target covers only:
- Step 1: create realistic, self-contained customer questions
- Step 2: generate draft LLM responses for those questions

Do not do Step 3 or Step 4 (defined in the [Producing Golden Datasets](https://github.com/microsoft/promptflow-resource-hub/blob/main/sample_gallery/golden_dataset/copilot-golden-dataset-creation-guidance.md)):
- Do not write expert answers
- Do not present draft answers as validated or final
- Do not invent citations or source references that are not supported by the provided materials

Requirements:
- Produce a reviewable starter batch with exactly 12 items unless the user explicitly asks for a different count.
- Questions must sound like realistic non-expert customer questions.
- Every question must be self-contained and unambiguous.
- Cover the major domain areas visible in the provided materials.
- Prefer common customer-style openings such as `How do I...`, `What is...`, `Can you give me...`, `Why should I...`, and `What are the recommended best practices for ...`.
- Draft LLM responses should be helpful and plausible, but clearly framed as starting points for later expert review.
- Keep each draft response concise but complete enough for a domain expert to refine.
- If grounding is weak, narrow the question or add a short caveat inside the draft response rather than overstating certainty.
- The rendered output should be easy to export into a CSV file in the `output/` directory with `Question` and `Answer` columns, plus `Content` when available.
- Quality metrics such as `Similarity`, `Relevance`, `Coherence`, and `Groundedness` are generated after export by the bundled script at `scripts/generate_quality_metrics.py` targeting the CSV in the `output/` folder.
- Include `content` for every item. This should be the supporting RAG content that best matches the question and draft answer and will be used later for meaningful `Groundedness` evaluation.
- Treat the following metric guidance as best practice during evaluation:
  - `Similarity`: measures how similar the response is to a human expert answer. Scale `1-5`. Suggested goal: `3+`.
  - `Relevance`: measures how relevant the response is to the question and context. Scale `0-100`. Suggested goal: `60+`.
  - `Coherence`: measures the quality of the sentences and how naturally they fit together. Scale `1-5`. Suggested goal: `3+`.
  - `Groundedness`: measures how verifiable the answer is against the provided context. Scale `1-5`. Suggested goal: `3+`.
- Return the final result by calling `render_target_output` with JSON that strictly matches the schema below.

## Schema

```json
{
  "type": "object",
  "required": [
    "dataset_name",
    "domain",
    "recommended_total_dataset_size",
    "coverage_areas",
    "items"
  ],
  "additionalProperties": false,
  "properties": {
    "dataset_name": {
      "type": "string"
    },
    "domain": {
      "type": "string"
    },
    "recommended_total_dataset_size": {
      "type": "integer",
      "minimum": 1
    },
    "coverage_areas": {
      "type": "array",
      "items": {
        "type": "string"
      }
    },
    "items": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": [
          "id",
          "coverage_area",
          "question",
          "draft_llm_response",
          "content"
        ],
        "additionalProperties": false,
        "properties": {
          "id": {
            "type": "string"
          },
          "coverage_area": {
            "type": "string"
          },
          "question": {
            "type": "string"
          },
          "draft_llm_response": {
            "type": "string"
          },
          "content": {
            "type": "string"
          }
        }
      }
    }
  }
}
```

## Render Spec

```json
[
  { "type": "heading", "level": 1, "value": "Golden Dataset Starter: {dataset_name}" },
  { "type": "text", "value": "Domain: {domain}" },
  { "type": "text", "value": "Recommended full dataset size: {recommended_total_dataset_size} question-answer pairs" },
  { "type": "heading", "level": 2, "value": "Coverage Areas" },
  { "type": "bullet_list", "path": "coverage_areas" },
  { "type": "heading", "level": 2, "value": "Starter Question Set" },
  { "type": "repeat", "path": "items", "body": [
    { "type": "separator", "value": "---" },
    { "type": "heading", "level": 3, "value": "{item.id}. {item.coverage_area}" },
    { "type": "text", "value": "Question: {item.question}" },
    { "type": "text", "value": "Answer: {item.draft_llm_response}" },
    { "type": "text", "value": "Content: {item.content}" }
  ]},
  { "type": "heading", "level": 2, "value": "Scoring Workflow" },
  { "type": "text", "value": "After exporting a CSV with Question and Answer columns to the `output/` directory, run `python research_agent/skills/golden_dataset/scripts/generate_quality_metrics.py output/<input.csv>` from the deep_research folder to append Similarity, Relevance, Coherence, and Groundedness columns. Content is optional for metric calculation, but recommended because Groundedness is stronger when judged against supporting RAG material." },
  { "type": "text", "value": "Evaluation best practice: Similarity measures closeness to a human expert answer on a 1-5 scale with a suggested goal of 3+. Relevance measures how well the answer addresses the question and content on a 0-100 scale with a suggested goal of 60+. Coherence measures how naturally the sentences fit together on a 1-5 scale with a suggested goal of 3+. Groundedness measures how verifiable the answer is against the provided content on a 1-5 scale with a suggested goal of 3+." },
  { "type": "heading", "level": 2, "value": "Reviewer Note" },
  { "type": "text", "value": "These draft responses cover Golden Dataset steps 1 and 2 only. A domain expert should review and replace them with authoritative expert answers before evaluation use." }
]
```

## Quality Guidelines

Before submitting, verify every item passes:

- **Item count**: Exactly 12 items are present unless the user explicitly requested a different count.
- **Question realism**: Every question sounds like a real customer inquiry — avoid academic or overly technical phrasing. Prefer openings such as "How do I…", "What is…", "Can you give me…".
- **Self-contained questions**: Each question must be understandable on its own without referencing other items in the dataset.
- **No duplicate questions**: No two items should ask the same question with different wording.
- **Coverage balance**: Items should spread across the listed `coverage_areas`; no single area should dominate more than 40% of the dataset.
- **Grounding**: Every draft response must be traceable to the provided documents or research findings. Do not invent facts, statistics, or source references that are not supported by the materials.
- **Content capture**: Every item must include `content` containing the grounding RAG passage or summary that best supports the draft answer. Groundedness scoring depends on it.
- **Caveat over certainty**: If grounding is weak for a particular answer, narrow the question scope or add a short caveat rather than overstating confidence.
- **Draft framing**: Draft responses must be clearly framed as starting points — do not present them as validated expert answers.
- **Response completeness**: Each `draft_llm_response` must be substantive enough (3+ sentences) for a domain expert to meaningfully review and refine.
- **Metric readiness**: The output must be directly exportable to a CSV in the `output/` directory with `Question` and `Answer` columns for scoring with `generate_quality_metrics.py`. `Content` is recommended, especially for better Groundedness evaluation.
- **Schema compliance**: Output contains only schema-allowed fields (`dataset_name`, `domain`, `recommended_total_dataset_size`, `coverage_areas`, `items`, `id`, `coverage_area`, `question`, `draft_llm_response`, `content`).
