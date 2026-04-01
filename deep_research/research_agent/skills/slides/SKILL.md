---
name: slides
title: Learning Slides
description: Quick-learning presentation markup with fewer than 3 slides and speaking notes.
render_template: markdown_blocks
---

## Instructions

Create concise Markdown presentation content for quick learning.

- Keep it to fewer than 3 slides.
- Use clear slide titles.
- Use concise bullets.
- Include speaking notes for each slide.
- Ground the content in the available documents and research findings.
- Return the final result by calling `render_target_output` with JSON matching the schema below.

## Schema

```json
{
  "type": "object",
  "required": ["topic", "slides"],
  "additionalProperties": false,
  "properties": {
    "topic": {
      "type": "string"
    },
    "slides": {
      "type": "array",
      "maxItems": 2,
      "items": {
        "type": "object",
        "required": ["title", "bullets", "speaker_notes"],
        "additionalProperties": false,
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

## Render Spec

```json
[
  { "type": "heading", "level": 1, "value": "Presentation: {topic}" },
  { "type": "repeat", "path": "slides", "body": [
    { "type": "separator", "value": "---" },
    { "type": "heading", "level": 2, "value": "Slide {index}: {item.title}" },
    { "type": "bullet_list", "path": "item.bullets" },
    { "type": "if_present", "path": "item.speaker_notes", "body": [
      { "type": "heading", "level": 3, "value": "Speaking Notes" },
      { "type": "text", "value": "{item.speaker_notes}" }
    ]}
  ]}
]
```
