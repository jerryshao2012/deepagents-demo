---
name: slides
title: Learning Slides
description: Quick-learning presentation markup with fewer than 5 slides and speaking notes.
render_template: markdown_blocks
---

## Instructions

Create concise Markdown presentation content for quick learning.

- Keep it to fewer than 5 slides.
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
      "maxItems": 5,
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

## Quality Guidelines

Before submitting, verify every item passes:

- **Slide count**: The presentation contains at most 2 slides (enforced by `maxItems: 5` in the schema).
- **Grounding**: Every bullet point and speaking note must be traceable to the provided documents or research findings. Do not invent unsupported claims.
- **No filler content**: Remove generic bullets such as "In conclusion…" or "As we can see…" that add no informational value.
- **Title clarity**: Each slide title should clearly describe the content of that slide in fewer than 10 words.
- **Bullet conciseness**: Each bullet should be one sentence or phrase. If a bullet exceeds two lines, split it or shorten it.
- **Speaker notes depth**: Speaking notes must add context beyond what the bullets already say — explanations, examples, or transition cues.
- **Schema compliance**: Output contains only schema-allowed fields (`topic`, `slides`, `title`, `bullets`, `speaker_notes`).
