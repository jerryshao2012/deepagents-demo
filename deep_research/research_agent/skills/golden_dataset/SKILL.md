---
name: golden-dataset
title: Golden Dataset Starter
description: Produce a Golden Dataset starter pack with realistic customer questions and draft LLM answers only. Use for deep research outputs that should cover Golden Dataset steps 1 and 2, then score the exported CSV separately with the bundled quality-metrics script.
render_template: markdown_blocks
keywords:
  - "golden-dataset"
  - "golden dataset"
  - "golden.*dataset"
  - "create.*ga.*pair"
  - "question.*answer"
  - "golden_dataset"
defaults:
  - field: domain
    if_null: true
    value: "first_of: domain, coverage_areas"
  - field: domain
    if_null: true
    value: General
  - field: coverage_areas
    if_null: true
    value: "collect_unique:coverage_area"
  - field: dataset_name
    if_null: true
    value: derive_dataset_name
  - field: recommended_total_dataset_size
    if_null: true
    value: dataset_size_calc
  - field: items
    value: ensure_item_ids
  - field: items
    value: ensure_item_content
---

## Instructions

Create a Golden Dataset starter pack grounded in the available documents and research findings.

This skill covers only:
- Step 1: create realistic, self-contained customer questions
- Step 2: generate draft LLM responses for those questions

Do not do Step 3 or Step 4 (defined in the [Producing Golden Datasets](https://github.com/microsoft/promptflow-resource-hub/blob/main/sample_gallery/golden_dataset/copilot-golden-dataset-creation-guidance.md)):
- Do not write expert answers
- Do not present draft answers as validated or final
- Do not invent citations or source references that are not supported by the provided materials

Requirements:
- **ROLE SPLIT — who does what:**
  - The main agent **orchestrator** performs the DOCUMENT ACCESS WORKFLOW (below) using local filesystem/document tools, prepares grounded context, and coordinates the final output tool sequence.
  - The **research sub-agent** is web-only (`tavily_search`, `fetch_webpage_content`), drafts the 12 Q/A items using orchestrator-provided grounding plus optional web evidence, and returns the full JSON payload (matching the schema) to the orchestrator. The sub-agent does **not** call `render_skill_output` or `finalize_golden_dataset_output`.
- **COMPLETION SEQUENCE (orchestrator only) — follow these steps in order after the sub-agent returns the drafted items:**
  1. Call `render_skill_output` with `skill_id="golden-dataset"` and the sub-agent's JSON object (including `items`). This validates the payload and returns the Markdown preview.
  2. Call `finalize_golden_dataset_output` with the **same JSON string** as step 1. Implementation lives under `research_agent/skills/golden_dataset/` (`pipeline.py`): it writes the CSV to `./output/`, runs evaluation, generates a markdown table and calls `write_todos` to save as `/golden_dataset_metrics.md`, and creates a comprehensive final report and calls `write_todos` to save as `/final_report.md` in one atomic step.
  3. Call `write_todos` to mark ALL todos as "completed".
  4. Only after steps 1–3 succeed, write a brief summary to the user.
  **Do NOT skip steps 1, 2, or 3. A verbal description of the dataset is NOT a substitute for the tool calls.**
 **DOCUMENT ACCESS WORKFLOW (orchestrator only)**:
  - Step 1: Call `read_doc_folder` exactly once on the configured doc folder (e.g., `./docs/policy/`). This extracts documents and returns saved paths like `output/policy/extracted/filename.pdf_extracted.md`.
  - Step 2: Use the EXACT extracted paths with `read_file` as `output/policy/extracted/file.md` (do NOT add leading `/`).
  - Step 3: If `ls` or `glob` returns paths starting with `/` (for example `/output/policy/extracted/...`), strip the leading `/` before `read_file`.
  - Step 4: Build grounded notes/snippets from extracted markdown files and pass them into the sub-agent task prompt for drafting.
  - Step 5: Sub-agent returns the full JSON payload to orchestrator; orchestrator then runs `render_skill_output` and `finalize_golden_dataset_output`.- Produce a reviewable starter batch with exactly 12 items unless the user explicitly asks for a different count.
- Questions and answers are based on extracted knowledge documents in markdown format from `./output/<sub-folder>/extracted/` (NOT from `./docs/<sub-folder>/`). For example, if documents were provided from `./docs/policy/`, read the extracted content from `./output/policy/extracted/`. Use `read_file` or filesystem tools to access these pre-extracted markdown files.
- Questions must sound like realistic non-expert customer questions.
- Every question must be self-contained and unambiguous.
- Cover the major domain areas visible in the provided materials.
- Prefer common customer-style openings such as `How do I...`, `What is...`, `Can you give me...`, `Why should I...`, and `What are the recommended best practices for ...`.
- Answers should be helpful and plausible, but clearly framed as starting points for later expert review.
- Keep each answer concise but complete enough for a domain expert to refine.
- If grounding is weak, narrow the question or add a short caveat inside the answer rather than overstating certainty.
- **Complete the full dataset in one pass. Do NOT stop mid-generation to ask the user which topics to prioritize, which areas to cover, or for any other confirmation. Make all topic and coverage choices autonomously based on the available documents.**
- The rendered output should be easy to export into a CSV file in the `./output/` directory with `Question` and `Answer` columns, plus `Content` when available.
- Quality metrics such as `Similarity`, `Relevance`, `Coherence`, and `Groundedness` are automatically generated by `finalize_golden_dataset_output`, which exports the CSV, evaluates quality, creates a markdown table at `/golden_dataset_metrics.md`, and produces a comprehensive final report at `/final_report.md`.
- The final report includes quality metrics summary, detailed metrics table, goal achievements, and recommendations for improvement.
- Include `content` for every item. This should be the supporting RAG content that best matches the question and answer and will be used later for meaningful `Groundedness` evaluation.
- Treat the following metric guidance as best practice during evaluation:
  - `Similarity`: measures how similar the response is to a human expert answer. Scale `1-5`. Suggested goal: `3+`.
  - `Relevance`: measures how relevant the response is to the question and context. Scale `0-100`. Suggested goal: `60+`.
  - `Coherence`: measures the quality of the sentences and how naturally they fit together. Scale `1-5`. Suggested goal: `3+`.
  - `Groundedness`: measures how verifiable the answer is against the provided context. Scale `1-5`. Suggested goal: `3+`.
- **Important**: The schema distinguishes between `coverage_areas` (plural) at the top level and `coverage_area` (singular) for each individual item. Both are required in their respective locations.

## Schema

```json
{
  "type": "object",
  "required": ["items"],
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
          "answer"
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
          "answer": {
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
    { "type": "text", "value": "Answer: {item.answer}" },
    { "type": "text", "value": "Content: {item.content}" }
  ]},
  { "type": "heading", "level": 2, "value": "Scoring Workflow" },
  { "type": "text", "value": "The `finalize_golden_dataset_output` tool automatically handles the complete evaluation workflow:" },
  { "type": "bullet_list", "items": [
    "Exports the dataset to CSV in the `./output/` directory",
    "Runs quality metrics evaluation (Similarity, Relevance, Coherence, Groundedness)",
    "Generates `/golden_dataset_metrics.md` with a markdown table of all items and their metrics",
    "Creates `/final_report.md` with comprehensive analysis including summary statistics, goal achievements, and recommendations. The report is automatically rewritten to remove AI writing patterns before saving."
  ]},
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
- **Response completeness**: Each `answer` must be substantive enough (3+ sentences) for a domain expert to meaningfully review and refine.
- **Metric readiness**: The output must be directly exportable to a CSV in the `./output/` directory with `Question` and `Answer` columns for scoring with `generate_quality_metrics.py`. `Content` is recommended, especially for better Groundedness evaluation.
- **Schema compliance**: Output contains only schema-allowed fields:
   - Top-level: `dataset_name`, `domain`, `recommended_total_dataset_size`, `coverage_areas` (array), `items`.
   - Item-level: `id`, `coverage_area` (string), `question`, `answer`, `content`.
- **Sequential IDs**: Ensure `id` for each item is a sequential string starting from "1".

### Handling Large Scale Datasets

If the `doc-folder` contains thousands of files or very large files (hundreds of GBs):

1. **Initial Extraction**: First, call `read_doc_folder` on the configured doc folder (e.g., `./docs/policy/`) to trigger extraction of documents. The output will show paths like "saved to output/policy/extracted/filename.pdf_extracted.md".
2. **Access Extracted Content**: Use the EXACT paths from the extraction output. If using filesystem tools (`ls`, `glob`, `read_file`) and they return paths starting with `/`, strip the leading `/` to make them relative (e.g., convert `/output/policy/extracted/file.md` to `output/policy/extracted/file.md`).
3. **Selective Sampling**: If there are many extracted files, identify a representative subset based on filenames or subfolders. If the research subject is broad or mentions no specific area, **automatically sample a diverse set of extracted files** to cover a range of topics without asking for confirmation.
4. **Iterative Coverage**: If needed, repeat the process for different "coverage areas" to ensure the items are well-distributed across the entire dataset.
5. **Summarization**: For very large individual extracted documents, focus on their executive summaries or introductions if available.
