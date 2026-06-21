# LLM Wiki

A script-first Deep Agents example that builds a persistent local wiki.

## How it works

This example implements a workflow where an agent researches a topic and writes the result into a local directory workspace.

The agent is given source material and questions, then gathers information, organizes it, and incrementally builds a
reusable wiki that future agents can reference. Over time, the wiki evolves through ingest, query, and lint passes
instead of restarting from scratch on every run.

`ingest`, `query`, and `lint` are powered by Deep Agents (`create_deep_agent`) running in LangSmith Sandbox: the query
pass reads the current wiki state, reasons over relevant pages, produces a grounded answer, and can file durable results
back into `wiki/query/` when useful.

## Structure

- `runner.py` - thin CLI entrypoint
- `helpers.py` - shared helpers, CLI parsing, and mode orchestration
- `index.py` - `wiki/index.md` catalog builder and categorization logic
- `log.py` - `log.md` append-only timeline formatter and writer
- `models.py` - shared config/dependency/result dataclasses
- `init.py` - `init` mode workflow
- `ingest.py` - `ingest` mode source expansion + review/apply flow
- `query.py` - `query` mode analysis + optional durable filing flow
- `lint.py` - `lint` mode health-check reconciliation flow
- `README.md` - setup and usage
- `pyproject.toml` - example-local dependency config

## Workspace layout

`init` creates this top-level layout in the wiki directory:

- `AGENTS.md` - wiki schema/config and workflow rules the LLM follows for ingest/query/lint. `init` creates it when
  missing and preserves existing edits on re-runs.
- `raw/` - immutable source files dropped in for ingest (articles, notes, datasets).
- `wiki/` - LLM-maintained knowledge pages (entities, concepts, summaries, syntheses).
- `wiki/index.md` - content-oriented catalog for wiki navigation and retrieval: categorized page links with one-line
  summaries and optional metadata (for example date/source count). Query flows read this first.
- `log.md` - append-only chronological interaction log. Every ingest/query/lint phase appends a parseable heading:
  `## [YYYY-MM-DD] mode.phase | outcome=...`, plus timestamp/summary bullets.

## Requirements

- Python 3.11+
- Appropriate model provider API keys (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) configured in your environment

## Setup

```bash
# From the llm-wiki directory:
uv sync
source .venv/bin/activate
```


## Usage

```bash
# Initialize a wiki directory layout
uv run --project llm-wiki \
  python llm-wiki/runner.py \
  --mode init \
  --wiki-dir ./my-ada-wiki \
  --topic "Ada Lovelace"

# Ingest source notes into canonical wiki pages (file + folder)
uv run --project llm-wiki \
  python llm-wiki/runner.py \
  --mode ingest \
  --wiki-dir ./my-ada-wiki \
  --source ./notes/ada.md \
  --source ./notes/speeches/

# Ask grounded questions against the maintained wiki
uv run --project llm-wiki \
  python llm-wiki/runner.py \
  --mode query \
  --wiki-dir ./my-ada-wiki \
  --question "What did Ada contribute to computing?"

# Run a wiki maintenance pass (fix links, deduplicate pages, refresh index.md, append log.md entry)
uv run --project llm-wiki \
  python llm-wiki/runner.py \
  --mode lint \
  --wiki-dir ./my-ada-wiki

# Optional flags:
#   --review             # ingest only: review before apply
#   --topic "Name"       # set custom topic name (defaults to folder name)
```

## Ingest workflow

`ingest` applies directly by default.

If you pass `--review`, ingest becomes a two-phase, operator-in-the-loop flow:

1. Review phase (read-only): the model reads staged source files and returns key takeaways, proposed wiki updates,
   contradictions, and index updates.
2. Apply phase (write): after your confirmation, the model writes canonical concept/entity/theme updates and integrates
   evidence directly into those pages.
3. The runner refreshes `wiki/index.md` and appends structured `ingest.review` / `ingest.apply` timeline entries in
   `log.md`.
4. In `--review` mode, declining confirmation skips wiki edits, but still appends an `ingest.apply | outcome=canceled`
   entry.

Batch ingest is the default. A single run can process multiple files and directories.

## Query workflow

`query` runs in two phases automatically:

1. Analysis phase (read-only): the model reads `wiki/index.md`, then recent `log.md` entries for recency context, then (
   when helpful) checks prior `wiki/query/*.md` pages for discovery/routing, expands into canonical wiki pages for
   grounding, answers with citations, and decides whether the result should be filed for future reuse. Query pages are
   treated as routing hints rather than primary evidence.
2. Filing phase (write, conditional): if the answer is durable, the runner files it into `wiki/query/<question-slug>.md`
   and refreshes `wiki/index.md`.
3. The runner always appends structured query timeline entries (`query.review` and optionally `query.apply`) to `log.md`
   so query history is complete, even on `skip`.

## Lint workflow

`lint` is single-pass and applies immediately:

1. Health-check phase (apply): the model reads recent `log.md` entries for recency context, then reconciles
   contradictions, stale/superseded claims, orphan pages, missing cross-references, and key concept coverage directly in
   `/wiki/` (creating new canonical pages when needed).
2. Gap reporting phase (in response): the model returns a concise summary with reconciled changes, remaining gaps, and
   suggested next questions/sources.
3. The runner refreshes `wiki/index.md`, appends a structured `lint.apply` entry to `log.md`.

## Log timeline

`log.md` is runner-managed, append-only, and designed to be parseable with simple shell tools.

- The agent should not edit `log.md` directly; the runner appends entries.
- Every interaction is recorded:
    - `ingest.review` (when `--review` is enabled)
    - `ingest.apply` (`outcome=applied` or `outcome=canceled`)
    - `query.review` (`outcome=file` or `outcome=skip`)
    - `query.apply` (only when filing, `outcome=filed`)
    - `lint.apply` (`outcome=applied`)
- Entry shape:
    - Heading: `## [YYYY-MM-DD] mode.phase | outcome=... key=value ...`
    - Body bullets: `timestamp` (UTC) and `summary`

```bash
# Show the latest 5 timeline entries.
grep "^## \\[" log.md | tail -5

# Show the latest query review outcomes.
grep "^## \\[.*\\] query.review \\|" log.md | tail -10
```
