---
name: interview
title: Interview Kit
description: A grounded 45-minute interview question kit with time-boxed questions and follow-up prompts.
render_template: interview_kit
---

## Instructions

Create a grounded 45-minute interview question kit based on the available documents and research findings.

- Include a short interview objective.
- Include time-boxed interview questions.
- Include follow-up prompts for each question.
- Keep the output grounded in the provided materials.
- Return the final result by calling `render_target_output` with JSON resembling the template below.

## Suggested Template

```json
{
  "type": "object",
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
