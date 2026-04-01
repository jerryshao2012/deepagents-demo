---
name: golden-dataset
title: Golden Dataset Starter
description: Produce a Golden Dataset starter pack with realistic customer questions and draft LLM answers only. Use for deep research outputs that should cover Golden Dataset steps 1 and 2, not expert-reviewed answers.
render_template: markdown_blocks
---

## Instructions

Create a Golden Dataset starter pack grounded in the available documents and research findings.

This target covers only:
- Step 1: create realistic, self-contained customer questions
- Step 2: generate draft LLM responses for those questions

Do not do Step 3 or Step 4 (Reference No. 1 material in References section):
- Do not write expert answers
- Do not present draft answers as validated or final
- Do not invent citations or source references that are not supported by the provided materials

Requirements:
- Produce a reviewable starter batch with exactly 12 items unless the user explicitly asks for a different count.
- Export the Golden Dataset to a CSV format file with “Question” and “Answer” columns at a minimum. With quality metrics columns such as "Similarity", "Relevance", "Coherence", and "Groundedness".
- Questions must sound like realistic non-expert customer questions.
- Every question must be self-contained and unambiguous.
- Cover the major domain areas visible in the provided materials.
- Typical questions start with:
  - Are there...?
  - Can you give me...?
  - How can I...?
  - How do I know...?
  - How do I...?
  - How does...?
  - How often...?
  - How should I...?
  - Is it possible...?
  - Should I...?
  - Tell me about...
  - What about...?
  - What are...?
  - What is...?
  - What's the best way...?
  - Why should I...?
  - What are the recommended best practices for ...?
- Draft LLM responses should be helpful and plausible, but clearly framed as starting points for later expert review.
- Keep each draft response concise but complete enough for a domain expert to refine.
- If grounding is weak, narrow the question or add a short caveat inside the draft response rather than overstating certainty.
- Once have the question and answer, measure the quality of LLM responses for your LLM. Here Prompt flow can be used to measure all the relevant metrics: GPT similarity; Relevance; Coherence and Groundedness.

After each evaluation, metrics like the following will be available to quantify the user experience. For example:

| Similarity  | Relevance  | Coherence  | Groundedness  |
|-------------|------------|------------|---------------|
| 3.7         | 77         | 88         | 69            |

What follows is a description and the suggested goals for these metrics (please see the [online documentation](https://learn.microsoft.com/azure/machine-learning/prompt-flow/how-to-bulk-test-evaluate-flow?view=azureml-api-2#understand-the-built-in-evaluation-metrics) for more information):

| Name                                     | Description                                                                                                                                                                                                                                                                                                                                                                                                   |
|------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| QnA Similarity Evaluation                | Measures how similar the responses from LLM are to the human expert.  Similarity is scored on a scale of 1 to 5, with 1 being the worst and 5 being the best.    Suggested Goal: 3+.                                                                                                                                                                                                                          |
| QnA Relevance Scores Pairwise Evaluation | Measure of how relevant the response is to the context provided.  0-20: the answer completely lacks confidence.  20-40: the answer mostly lacks confidence  40-60: the answer is partially confidence  60-80: the answer is mostly confidence  80-100: the answer has perfect confidence    Coherence is scored on a scale of 0 to 100, with 1 being the worst and 100 being the best.    Suggested Goal: 60+ |
| QnA Coherence Evaluation                 | Measures the quality of all sentences in a model's predicted answer and how they fit together naturally.  Coherence is scored on a scale of 1 to 5, with 1 being the worst and 5 being the best.    Suggested Goal: 3+                                                                                                                                                                                        |
| QnA Groundedness Evaluation              | Measure of how grounded the model's predicted answers are against the context. Even if LLM’s responses are true, if not verifiable against context, then such responses are considered ungrounded.  Groundedness metric is scored on a scale of 1 to 5, with 1 being the worst and 5 being the best.    Suggested Goal: 3+                                                                                    |
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
          "similarity",
          "relevance",
          "coherence",
          "groundedness"
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
          "similarity": {
            "type": "number"
          },
          "relevance": {
            "type": "number"
          },
          "coherence": {
            "type": "number"
          },
          "groundedness": {
            "type": "number"
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
    { "type": "text", "value": "Draft LLM Response: {item.draft_llm_response}" },
    { "type": "number", "value": "QnA Similarity Evaluation: {item.similarity}" },
    { "type": "number", "value": "QnA Relevance Evaluation: {item.relevance}"},
    { "type": "number", "value": "QnA Coherence Evaluation: {item.coherence}" },
    { "type": "number", "value": "QnA Groundedness Evaluation: {item.groundedness}"}
  ]},
  { "type": "heading", "level": 2, "value": "Reviewer Note" },
  { "type": "text", "value": "These draft responses cover Golden Dataset steps 1 and 2 only. A domain expert should review and replace them with authoritative expert answers before evaluation use." }
]
```

## References
1. [Producing Golden Datasets](https://github.com/microsoft/promptflow-resource-hub/blob/main/sample_gallery/golden_dataset/copilot-golden-dataset-creation-guidance.md)