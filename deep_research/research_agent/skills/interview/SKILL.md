---
name: interview
title: Interview Kit
description: A grounded 45-minute interview question kit with time-boxed questions and follow-up prompts.
render_template: markdown_blocks
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
  "required": ["topic", "objective", "questions"],
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
- Sum of all timebox_minutes equals 45.
- Exactly six interview questions are present in the middle section with the required difficulty progression.
- Output contains only schema-allowed fields.