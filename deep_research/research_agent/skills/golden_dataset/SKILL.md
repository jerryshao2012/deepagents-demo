---
name: golden_dataset
title: Golden Dataset Starter
description: Produce a Golden Dataset starter pack with realistic customer questions and draft LLM answers only. Use for deep research outputs that should cover Golden Dataset steps 1 and 2, then score the exported CSV separately with the bundled quality-metrics script.
render_template: markdown_blocks
---

## Instructions

Create a Golden Dataset starter pack grounded in the available documents and research findings.

This target covers only:
- Step 1: create realistic, self-contained customer questions
- Step 2: generate draft LLM responses for those questions

Do not do Step 3 or Step 4:
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
- The rendered output should be easy to export into CSV with at least `Question` and `Answer` columns.
- Quality metrics such as `Similarity`, `Relevance`, `Coherence`, and `Groundedness` are generated after export by the bundled script at `scripts/generate_quality_metrics.py`.
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
          "draft_llm_response"
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
    { "type": "text", "value": "Answer: {item.draft_llm_response}" }
  ]},
  { "type": "heading", "level": 2, "value": "Scoring Workflow" },
  { "type": "text", "value": "After exporting a CSV with at least Question and Answer columns, run `python research_agent/skills/golden_dataset/scripts/generate_quality_metrics.py <input.csv>` from the deep_research folder to append Similarity, Relevance, Coherence, and Groundedness columns." },
  { "type": "text", "value": "Evaluation best practice: Similarity measures closeness to a human expert answer on a 1-5 scale with a suggested goal of 3+. Relevance measures how well the answer addresses the question and context on a 0-100 scale with a suggested goal of 60+. Coherence measures how naturally the sentences fit together on a 1-5 scale with a suggested goal of 3+. Groundedness measures how verifiable the answer is against the provided context on a 1-5 scale with a suggested goal of 3+." },
  { "type": "heading", "level": 2, "value": "Reviewer Note" },
  { "type": "text", "value": "These draft responses cover Golden Dataset steps 1 and 2 only. A domain expert should review and replace them with authoritative expert answers before evaluation use." }
]
```
