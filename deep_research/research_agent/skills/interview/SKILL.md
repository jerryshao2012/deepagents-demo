---
name: interview
title: Interview Kit
description: A grounded 45-minute interview question kit with time-boxed questions and follow-up prompts.
render_template: markdown_blocks
---

## Instructions

Create a grounded 45-minute interview question kit based on the available documents and research findings.

- Include a short interview objective.
- Include time-boxed interview questions.
- Include follow-up prompts for each question.
- Keep the output grounded in the provided materials.
- Return the final result by calling `render_target_output` with JSON matching the schema below.

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
        "required": ["question", "timebox_minutes", "follow_up"],
        "additionalProperties": false,
        "properties": {
          "question": {
            "type": "string"
          },
          "timebox_minutes": {
            "type": "integer",
            "minimum": 1
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
    { "type": "text", "value": "Follow-up: {item.follow_up}" }
  ]},
  { "type": "text", "value": "Total planned time: {sum(questions[].timebox_minutes)} minutes" },
  { "type": "heading", "level": 2, "value": "Grounding Reminder" },
  { "type": "text", "value": "Tie every question back to the documents and research findings." }
]
```
