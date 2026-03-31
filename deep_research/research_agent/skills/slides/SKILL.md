---
name: slides
title: Learning Slides
description: Quick-learning presentation markup with fewer than 3 slides and speaking notes.
render_template: presentation
---

## Instructions

Create concise Markdown presentation content for quick learning.

- Keep it to fewer than 3 slides.
- Use clear slide titles.
- Use concise bullets.
- Include speaking notes for each slide.
- Ground the content in the available documents and research findings.
- Return the final result by calling `render_target_output` with JSON resembling the template below.

## Suggested Template

```json
{
  "type": "object",
  "properties": {
    "topic": {
      "type": "string"
    },
    "slides": {
      "type": "array",
      "maxItems": 2,
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string"
          },
          "bullets": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "speaker_notes": {
            "type": "string"
          }
        }
      }
    }
  }
}
```
