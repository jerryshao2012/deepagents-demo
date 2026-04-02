---
name: interview
title: Interview Kit
description: A grounded 45-minute interview question kit with time-boxed questions and follow-up prompts.
render_template: markdown_blocks
defaults:
  - field: topic
    if_null: true
    value: derive_topic
  - field: objective
    if_null: true
    value: derive_objective
---

## Instructions

Create a grounded 45-minute interview kit from the provided documents and research findings.

Requirements:
- Produce exactly 8 agenda items in questions so total planned time is exactly 45 minutes.
- Agenda structure must be:
  1. 5 minutes: self-introduction for interviewer and interviewee.
  2. 35 minutes: six interview questions, ordered by difficulty:
    - Q1-Q2: easy
    - Q3-Q4: harder
    - Q5-Q6: hardest
  3. 5 minutes: questions the interviewee asks the interviewer.
- Include a short topic string that describes the focus of the interview
- Include a short objective (1-2 sentences) describing what the interview is meant to assess.
- Every agenda item must include:
  - question
  - timebox_minutes
  - potential_answer (a brief outline of what a strong answer would include, grounded in the provided materials)
  - follow_up
- For the six interview questions, follow_up must probe depth (reasoning, tradeoffs, evidence, and practical application).
- Keep every question grounded in the provided materials; do not invent unsupported claims.
- If grounding is weak for a question, re-scope the question to match available evidence.
- Return the final result by calling `render_target_output` with JSON that strictly matches the schema below. 

## Schema

```json
{
  "type": "object",
  "required": ["questions"],
  "additionalProperties": false,
  "properties": {
    "topic": {
      "type": "string"
    },
    "objective": {
      "type": "string"
    },
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["question", "timebox_minutes", "follow_up", "potential_answer"],
        "additionalProperties": false,
        "properties": {
          "question": {
            "type": "string"
          },
          "timebox_minutes": {
            "type": "integer",
            "minimum": 1
          },
          "potential_answer": {
            "type": "string"
          },
          "follow_up": {
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
  { "type": "heading", "level": 1, "value": "Interview Kit: {topic}" },
  { "type": "heading", "level": 2, "value": "45-minute interview objective" },
  { "type": "text", "value": "{objective}" },
  { "type": "heading", "level": 2, "value": "Agenda" },
  { "type": "repeat", "path": "questions", "body": [
    { "type": "text", "value": "{index}. Timebox: {item.timebox_minutes} minutes" },
    { "type": "text", "value": "Question: {item.question}" },
    { "type": "text", "value": "Potential Answer: {item.potential_answer}" },
    { "type": "text", "value": "Follow-up: {item.follow_up}" }
  ]},
  { "type": "text", "value": "Total planned time: {sum(questions[].timebox_minutes)} minutes" },
  { "type": "heading", "level": 2, "value": "Grounding Reminder" },
  { "type": "text", "value": "Tie every question back to the documents and research findings." }
]
```

## Quality Guidelines

Before submitting, verify every item passes:

- **Total time**: Sum of all `timebox_minutes` equals exactly 45.
- **Agenda count**: Exactly 8 agenda items are present in `questions`.
- **Agenda structure**: Items follow the required order — 5-min intro, six interview questions, 5-min closing.
- **Difficulty progression**: The six interview questions escalate in difficulty (Q1-Q2 easy, Q3-Q4 harder, Q5-Q6 hardest).
- **Grounding**: Every question and potential answer must be traceable to the provided documents or research findings. Do not invent unsupported claims.
- **Potential answers**: Each `potential_answer` outlines what a strong response would include, grounded in the source materials — not a single-sentence restatement of the question.
- **Follow-up depth**: Each `follow_up` for interview questions probes reasoning, tradeoffs, evidence, or practical application — not a generic "Can you elaborate?".
- **Self-contained questions**: Each question must be understandable on its own without needing to read the previous question.
- **No filler**: Remove generic questions such as "Tell me about yourself" from the six interview slots; those belong only in the intro/closing items.
- **Schema compliance**: Output contains only schema-allowed fields (`topic`, `objective`, `questions`, `question`, `timebox_minutes`, `potential_answer`, `follow_up`).