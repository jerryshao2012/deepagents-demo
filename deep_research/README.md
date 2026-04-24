# 🚀 Deep Research

## 🚀 Quickstart

**Prerequisites**: Install [uv](https://docs.astral.sh/uv/) package manager:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

*Alternative installation for restricted corporate environments:*
```bash
pip install uv
```

Ensure you are in the `deep_research` directory:

```bash
cd deep_research
```

Install packages:

```bash
uv sync
```

* If `uv` is not available on your system path, you can ry: 
```bash
# In Windows if PATH is not setup properly
python -m uv sync
```
Note: use `uv sync --reinstall` to reinstall all packages if you see some errors.

Set your API keys in your environment:

```bash
# Option 1: Using Ollama (LOCAL - FREE)
export OLLAMA_API_BASE=http://localhost:11434
export MODEL_NAME=glm-4.7-flash:latest                    # or qwen3.5:latest, deepseek-r1:14b, etc.
export TAVILY_API_KEY=your_tavily_api_key_here            # ✅ Required for web search

# Option 2: Using Cloud APIs
export ANTHROPIC_API_KEY=your_anthropic_api_key_here      # For Claude model
export GOOGLE_API_KEY=your_google_api_key_here            # For Gemini model ([get one here](https://ai.google.dev/gemini-api/docs))
export TAVILY_API_KEY=your_tavily_api_key_here            # Required for web search ([get one here](https://www.tavily.com/)) with a generous free tier
export LANGCHAIN_TRACING_V2=true                          # Enable LangSmith tracing
export LANGSMITH_ENDPOINT=https://api.smith.langchain.com # LangSmith endpoint
export LANGCHAIN_API_KEY=your_langsmith_api_key_here      # [LangSmith API key](https://smith.langchain.com/settings) (free to sign up)
export LANGCHAIN_PROJECT=deep-research-deepagents         # The project name to log traces to

# Research Agent Configuration
# Maximum number of concurrent research units (sub-agents) that can run simultaneously
MAX_CONCURRENT_RESEARCH_UNITS=3
# Maximum number of iterations per researcher agent before stopping
MAX_RESEARCHER_ITERATIONS=3

# Filesystem and Output Configuration
# Maximum directory depth for glob pattern matching
MAX_GLOB_DEPTH=3
# Default output folder for generated reports and documents
REPORTS_OUTPUT_FOLDER=./output
# Maximum number of files to read in a single operation
MAX_FILES_TO_READ=20
# Maximum total size in MB for batch file reading operations
MAX_TOTAL_SIZE_MB=50

---

## 🛡️ Reliability & Rate Limiting

When building high-throughput agents, treating LLM providers as finite-capacity systems is critical. This project implements a dual-layer approach to ensure reliability:

### 1. Proactive Rate Shaping
Instead of waiting for `429 Too Many Requests` errors, the harness proactively controls the flow of tokens and requests. This is handled by the `AsyncRateLimiter` in `deep_research/retry_utils.py`.

- **TPM (Tokens Per Minute) Control**: Tracks a rolling 60-second window of estimated tokens to stay under deployment quotas.
- **RPM (Requests Per Minute) Pacing**: Ensures requests are evenly spaced to avoid triggering micro-burst limits (often 1–10 seconds).
- **Safe Margins**: Operates at ~80% of hard limits to absorb jitter and shared usage.

To enable, set these environment variables:
```properties
# Proactive Rate Shaping (TPM and RPM limits)
# Set these based on your provider's deployment quotas
# Tokens Per Minute:
# Represents the maximum number of tokens (input + output) you are allowed to send to the model provider within a
# rolling 60-second window.
MODEL_TPM=120000
# Requests Per Minute:
# Represents the maximum number of individual API calls you can make per minute.
MODEL_RPM=500
```

### 2. Reactive Retries
For unpredictable server-side issues or shared capacity drops, a reactive layer handles retries with **Exponential Backoff and Jitter**.

- **Jitter**: Prevents "thundering herd" problems by randomizing retry delays.
- **Header Respect**: Logic can be extended to respect `Retry-After` headers from providers.
- **Configurable**: Adjust `MODEL_MAX_RETRIES` and `MODEL_INITIAL_BACKOFF` as needed.

### Strategic Recommendations
1. **Estimate accurately**: Use `tiktoken` (integrated in `AsyncRateLimiter`) for precise token counting.
2. **Layer your defenses**: Always use proactive shaping *with* reactive retries.
3. **Deployment-specific limits**: Configure unique limits for different models or regions to maximize throughput.

---

## Usage Options

You can run this example in two ways:

### Option 1: Command Line Script

Run the standalone Python script to execute the research agent:

```bash
uv run python research_agent_cli.py "Research AI Agents"
```

#### Command Line Options

The CLI supports the following options:

```
positional arguments:
  subject               Research subject. If omitted, a subject file may be used instead.

optional arguments:
  --subject-file SUBJECT_FILE
                        Optional file path to read the research subject from
  --verify_ssl [VERIFY_SSL]
                        Verify SSL certificates (default: True). Set to False to skip SSL verification
  --ssl-ca-files SSL_CA_FILES
                        Path to a PEM CA bundle to use for HTTPS verification
  --verbose [VERBOSE]   Show progress (default: True). When False, runs agent without progress display
  --help, -h            Show this help message and exit
  --doc-folder DOC_FOLDER
                        Optional folder containing supported documents to use as research material
  --no-web              Disable web search (Tavily) during research
  --skill {list,<available-skill-ids>}
                        Optional structured output skill. Use '--skill list' to see all available skills.
  --title TITLE         Optional research title for output file naming
  --eval-golden-dataset Enable golden-dataset regression tracking and JSONL report output
  --eval-mode {baseline,candidate}
                        Evaluation mode for --eval-golden-dataset (default: candidate)
  --eval-history-file EVAL_HISTORY_FILE
                        Optional JSONL output file path for evaluation history.
                        Default: ./output/eval_history/golden_dataset_runs.jsonl
```

#### Examples

Basic research task:
```bash
uv run python research_agent_cli.py "Research AI Agents"
```

With document folder and structured output:
```bash
uv run python research_agent_cli.py "Research AI Agents" --doc-folder ./docs --skill study-slides
```

Generate an interview question kit:
```bash
uv run python research_agent_cli.py "Research AI Agents" --doc-folder ./docs --skill interview
```

Prepare a comprehensive interview with questions and answers:
```bash
uv run python research_agent_cli.py "Preparing a 60 minutes interview with list of question and answer" --doc-folder ./docs/interview_prep --skill interview-coach-pro
```

Generate a golden dataset:
```bash
uv run python research_agent_cli.py "Generate 20 question-answer pairs for the documents provided" --doc-folder ./docs/policy/ --skill golden-dataset
```

Create a baseline evaluation entry for a fixed golden-dataset test case:
```bash
uv run python research_agent_cli.py "Generate 5 question-answer pairs for the documents provided" --doc-folder ./docs/policy/ --skill golden-dataset --eval-golden-dataset --eval-mode baseline
```

Run a candidate evaluation and compare against the latest baseline with the same test input:
```bash
uv run python research_agent_cli.py "Generate 5 question-answer pairs for the documents provided" --doc-folder ./docs/policy/ --skill golden-dataset --eval-golden-dataset --eval-mode candidate
```

Write JSONL history to a custom location:
```bash
uv run python research_agent_cli.py "Generate 5 question-answer pairs for the documents provided" --doc-folder ./docs/policy/ --skill golden-dataset --eval-golden-dataset --eval-history-file ./output/eval_history/my_runs.jsonl
```

> Important: comparisons are only performed when the test case is exactly the same (same subject text, skill, doc-folder, model, and flags). Inputs like "Generate 5 pairs..." and "Generate 10 pairs..." are intentionally treated as non-comparable.

<img width="937" alt="Deep Research Agent Architecture" src="./resources/Deep_Research_Agent_with_Golden_Dataset_Generation_Skill.png" />

1.  **Context Injection**: A curated set of "Source-of-Truth" documents (PDFs, Markdown, or technical specs) is provided to the agent's filesystem, populating the 'Local Context (doc folder)'.

2.  **Synthesis-First, Prioritized Context Strategy**: The agent is instructed to prioritize the `[read_doc_folder]` tool for Knowledge Retrieval from the local filesystem as its primary source. The research logic, orchestrated by the harness and monitored by the `think_tool`, follows a clear priority strategy to always exhaust internal knowledge first.

3.  **Golden Dataset Skill (The Auditor)**:
    * **Question Generation**: It analyzes the provided (and potentially augmented) documents to identify key technical facts, contradictions, or complex logic.
    * **Context Pinpointing**: It maps the generated question directly to the specific localized context (e.g., paragraph or page in the local document).
    * **Answer Extraction**: It generates the "Ideal Answer" based strictly on that pinpointed source context.

4.  **Tavily as a Prioritized Fallback (Not Direct Tool Call)**: The system possesses a distinct, parallel `[tavily_search]` tool for external web search. Within the Context Strategy, it is treated as a prioritized fallback, meaning it is only triggered conceptually as a second priority if the provided local documents are explicitly incomplete. It is executed independently by the sub-agents and is generally flagged as "out-of-distribution" for the golden set, which is intended to be grounded in the internal dataset.

Generate code using code-generator skill:
```bash
uv run python research_agent_cli.py --subject-file ./input/coding-create-a-image.txt --skill code-generator
```

Without web search (using only local documents):
```bash
uv run python research_agent_cli.py "Research AI Agents" --doc-folder ./docs --no-web
```

Read subject from a file:
```bash
uv run python research_agent_cli.py --subject-file ./input/interview-subject.txt --doc-folder ./docs
```

Show available structured output skills:
```bash
uv run python research_agent_cli.py --skill list
```

Structured skills are skill-driven. Add a new `research_agent/skills/<skill>/SKILL.md`
with frontmatter, instructions, a JSON Schema block, and a render template to make a new
skill available through `--skill` without changing core CLI or tool wiring.

If you prefer an interactive notebook, you can still run it via:
```bash
uv run jupyter notebook research_agent.ipynb
```

### Option 2: LangGraph Server

Run a local [LangGraph server](https://langchain-ai.github.io/langgraph/tutorials/langgraph-platform/local-server/) with a web interface:

```bash
langgraph dev
```

LangGraph server will open a new browser window with the Studio interface, which you can submit your search query to:

<img width="1915" alt="Screenshot 2026-04-03 at 10 27 11 AM" src="./resources/Screenshot 2026-04-03 at 10 27 11 AM.png" />

You can also connect the LangGraph server to a [UI specifically designed for deepagents](https://github.com/langchain-ai/deep-agents-ui):

```bash
git clone https://github.com/langchain-ai/deep-agents-ui.git
cd deep-agents-ui

# Install yarn
npm config set "bin-links" true
npm config set "strict-ssl" false
npm install -g yarn
# Add %AppData%\npm to PATH for Windows

# For corporation network
yarn config set "strict-ssl" false
# Get configuration from npm config list
yarn config set registry <url>

yarn install
yarn dev
```

Then follow the instructions in the [deep-agents-ui README](https://github.com/langchain-ai/deep-agents-ui?tab=readme-ov-file#connecting-to-a-langgraph-server) to connect the UI to the running LangGraph server. Get the Deployment URL and Assistant ID from the terminal output and langgraph.json file, respectively:

- **Deployment URL**: http://127.0.1:2024
- **Assistant ID**: research

**Open Deep Agents UI** at [http://localhost:3000](http://localhost:3000) and input the Deployment URL and Assistant ID:

- **Deployment URL**: The URL for the LangGraph deployment you are connecting to
- **Assistant ID**: The ID of the assistant or agent you want to use
- [Optional] **LangSmith API Key**: Your LangSmith API key (format: `lsv2_pt_...`). This may be required for accessing deployed LangGraph applications. You can also provide this via the `NEXT_PUBLIC_LANGSMITH_API_KEY` environment variable.

This provides a user-friendly chat interface and visualization of files in state.

<img width="1917" alt="Screenshot 2026-04-03 at 12:44 11 PM" src="resources/Screenshot 2026-04-03 at 12 44 11 PM.png" />

Example:
```text
Generate 20 pair of question and answer using the `golden-dataset` skill for the documents provided in this folder '.\docs\policy\'.
```
```text
Give me an overview of AI Evaluation through Harness Engineering
```

## 🧩 Deep Research Agent Components

What is used in the deep research agent?

<img width="377" alt="Deep Research Graph" src="./resources/deep_research_graph.png" />

### 1. Planning (`write_todos`)
- **Workflow Orchestration**: The research workflow starts with creating a todo list using the `write_todos` tool to break down the user's research request into focused tasks.
- **Progress Tracking**: This list is used for task breakdown and ensures systematic research coverage.

### 2. Filesystem & Context Gathering
- **Document Reading**: A specialized `read_doc_folder` tool is used to extract text from various document formats, including:
  - PDF (`.pdf`)
  - Word (`.docx`)
  - PowerPoint (`.pptx`)
  - Excel (`.xlsx`)
  - Text and Markdown (`.txt`, `.md`)
- **Caching**: Extracted text from documents is cached under the active output folder (for example `output/` or `output/<doc-folder-name>/`) to avoid redundant processing.
- **Storage**: Findings and final reports are saved to files like `/research_request.md` and `/final_report.md` (using `write_file`).

### 3. Web Research Tools
- **Tavily Search**: The primary tool for web research is `tavily_search`, which performs web searches to gather information.
- **Webpage Fetching**: `fetch_webpage_content` is used to retrieve and process content from specific URLs found during searches.

### 4. Sub-Agents & Delegation
- **Delegation Strategy**: The orchestrator uses the `task()` tool (provided by the `deepagents` framework) to delegate specific research tasks to specialized sub-agents.
- **Parallel Execution**: Sub-agents can run in parallel for comparison tasks or multi-faceted research (configured in `agent.py`).
- **Context Isolation**: Each sub-agent operates within its own context, and findings are later synthesized by the orchestrator.

### 5. Smart Defaults & Prompting
- **Structured Prompts**: Extensive prompt templates in `research_agent/prompts.py` (e.g., `RESEARCH_WORKFLOW_INSTRUCTIONS`, `RESEARCHER_INSTRUCTIONS`) define detailed behaviors for:
  - Research planning and limits
  - Citation formatting (`[1]`, `[2]`...)
  - Report writing patterns (Comparisons, Lists, Summaries)
  - Tool usage rules (e.g., must use `think_tool` after each search)

### 6. Structured Output Skills
- **Structured Skills**: The agent can generate structured data using skills like `golden-dataset`.
- **Validation and Finalization**: Tools like `render_skill_output` and `finalize_golden_dataset_output` are used to validate schemas, export CSVs, and run or re-run quality metrics.

### 7. Context Management
- **Reflection**: The `think_tool` is used for "inner monologue" and strategic planning, helping the agent reflect on findings before deciding the next step.
- **Synthesis**: The orchestrator is responsible for consolidating findings and citations from all sub-agents into a final, coherent report.
- **Auto-summarization**: The underlying `deepagents` framework likely handles conversation pruning or summarization when context limits are reached.

## 📚 Resources

- **[Deep Research Course](https://academy.langchain.com/courses/deep-research-with-langgraph)** - Full course on deep research with LangGraph

### Custom Model

By default, `deepagents` uses `"claude-sonnet-4-5-20250929"`. You can customize this by passing any [LangChain model object](https://python.langchain.com/docs/integrations/chat/). See the Deep Agents package [README](https://github.com/langchain-ai/deepagents?tab=readme-ov-file#model) for more details.

```python
import os
from langchain.chat_models import init_chat_model
from deepagents import create_deep_agent

# Using Ollama (Local)
model = init_chat_model(model=f"ollama:{os.getenv("MODEL_NAME")}", base_url=os.getenv("OLLAMA_API_BASE"))

# Using Claude
model = init_chat_model(model=os.getenv("MODEL_NAME"), temperature = 0.0)

# Using Gemini
from langchain_google_genai import ChatGoogleGenerativeAI

model = ChatGoogleGenerativeAI(model=os.getenv("MODEL_NAME"))

# Using AzureOpenAI
from langchain_openai import AzureChatOpenAI
from pydantic import SecretStr

model = AzureChatOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    api_key=SecretStr(os.getenv("AZURE_OPENAI_API_KEY", ""))
)

agent = create_deep_agent(
    model=model,
)
```

### Custom Instructions

The deep research agent uses custom instructions defined in `research_agent/prompts.py` that complement (rather than duplicate) the default middleware instructions. You can modify these in any way you want.

| Instruction Set | Purpose |
|----------------|---------|
| `RESEARCH_WORKFLOW_INSTRUCTIONS` | Defines the 5-step research workflow: save request → plan with TODOs → delegate to sub-agents → synthesize → respond. Includes research-specific planning guidelines like batching similar tasks and scaling rules for different query types. |
| `SUBAGENT_DELEGATION_INSTRUCTIONS` | Provides concrete delegation strategies with examples: simple queries use 1 sub-agent, comparisons use 1 per element, multi-faceted research uses 1 per aspect. Sets limits on parallel execution (max 3 concurrent) and iteration rounds (max 3). |
| `RESEARCHER_INSTRUCTIONS` | Guides individual research sub-agents to conduct focused web searches. Includes hard limits (2-3 searches for simple queries, max 5 for complex), emphasizes using `think_tool` after each search for strategic reflection, and defines stopping criteria. |

### Custom Tools

The deep research agent adds the following custom tools beyond the built-in deepagent tools. You can also use your own tools, including via MCP servers. See the Deep Agents package [README](https://github.com/langchain-ai/deepagents?tab=readme-ov-file#mcp) for more details.

#### Web Search & Content Retrieval

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>tavily_search</code></td>
    <td>Advanced web search tool that uses Tavily purely as a URL discovery engine. Performs searches using Tavily API to find relevant URLs, fetches full webpage content via HTTP with proper User-Agent headers (avoiding 403 errors), converts HTML to markdown, and returns the complete content without summarization to preserve all information for the agent's analysis. Supports configurable result counts and topic filtering (general/news/finance). Respects the <code>no_web</code> state flag to disable web access when needed. Works with both Claude and Gemini models.</td>
  </tr>
  <tr>
    <td><code>fetch_webpage_content</code></td>
    <td>Fetches and converts a specific webpage URL to markdown format. Useful when you have a direct URL and need to extract its content for analysis. Uses proper User-Agent headers and respects SSL verification settings. Also checks the <code>no_web</code> state flag before fetching.</td>
  </tr>
</table>

#### Strategic Thinking & Reflection

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>think_tool</code></td>
    <td>Strategic reflection mechanism that helps the agent pause and assess progress between searches, analyze findings, identify gaps, and plan next steps. Records reflections to timestamped log files in the output folder for audit trails. Essential for maintaining coherent research strategy across multiple iterations.</td>
  </tr>
</table>

#### Filesystem & Document Processing

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>read_file</code></td>
    <td>Reads the content of a file at the given path. Implements a two-tier fallback strategy: first checks LangGraph state virtual filesystem (DeepAgents backend), then falls back to the local filesystem if not available. Normalizes paths for cross-platform compatibility.</td>
  </tr>
  <tr>
    <td><code>ls</code></td>
    <td>Lists the contents of a directory with fallback support. Tries virtual filesystem in state first, then local filesystem. Returns filenames with "/" suffix for subdirectories. Normalizes paths for consistent behavior across Windows and Unix systems.</td>
  </tr>
  <tr>
    <td><code>glob</code></td>
    <td>Finds files matching a glob pattern with recursive support (e.g., <code>**/*.md</code>). Implements dual-path resolution: virtual filesystem first, then local filesystem. Handles complex patterns and normalizes paths for cross-platform compatibility.</td>
  </tr>
  <tr>
    <td><code>read_doc_folder</code></td>
    <td>Extracts text content from supported document files in a specified folder. Supports <code>.pdf</code>, <code>.txt</code>, <code>.md</code>, <code>.docx</code>, <code>.pptx</code>, and <code>.xlsx</code> formats. Automatically resolves folder paths from agent state or environment variables. Caches extracted content under the active output folder to avoid redundant processing. For large folders, returns a summary instead of full content; use the <code>specific_files</code> parameter to target individual documents.</td>
  </tr>
</table>

#### Skill Management System

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>list_available_skills</code></td>
    <td>Lists all available skills registered in the dynamic skill registry with their descriptions. Scans the <code>research_agent/skills/</code> directory and extracts metadata from SKILL.md frontmatter. Helps the agent discover what specialized capabilities are available for structured output generation (e.g., frontend-slides, golden-dataset, interview-prep).</td>
  </tr>
  <tr>
    <td><code>read_skill_supporting_file</code></td>
    <td>Reads supporting files from a skill directory (e.g., CSS templates, style presets, HTML architecture guides, animation patterns). Use this when a skill's instructions reference external resources needed for implementation. Provides error messages with available file listings if the requested file doesn't exist.</td>
  </tr>
</table>

#### Structured Output Rendering

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>render_skill_output</code></td>
    <td>Generic skill renderer that loads a skill definition from <code>research_agent/skills/*/SKILL.md</code>, validates the provided JSON payload against that skill's schema, applies default values for optional fields, coerces data types, and renders the final Markdown output using template specifications. <strong>Use ONLY for structured skills with JSON schemas</strong>—do NOT use for unstructured markdown documents. Returns validation errors if the payload doesn't match the schema.</td>
  </tr>
</table>

#### Golden Dataset Generation & Evaluation

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>finalize_golden_dataset_output</code></td>
    <td>Golden-dataset only: validates the same JSON payload as <code>render_skill_output</code>, exports a CSV under the output folder via <code>skills/golden_dataset/pipeline.py</code>, then runs quality metrics so export and evaluation always happen in order. Generates human-readable quality reports (<code>final_report.md</code>) alongside raw metrics (<code>golden_dataset_metrics.md</code>). Persists files to LangGraph state for downstream access. Calculates chat elapsed time for performance tracking.</td>
  </tr>
</table>

#### Frontend Slides Presentation Generation

<table>
  <tr>
    <th width="250">Tool Name</th>
    <th>Description</th>
  </tr>
  <tr>
    <td><code>frontend-slides</code></td>
    <td>Generates self-contained HTML slide decks from markdown-style slide content. Accepts presentation content with headings (<code># [Slide 1] Title:</code>), headlines, subtitles, body text, bullet lists, and callout blocks. Supports 12 visual presets (Bold Signal, Electric Studio, Creative Voltage, Dark Botanical, Notebook Tabs, Pastel Geometry, Split Pastel, Vintage Editorial, Neon Cyber, Terminal Green, Swiss Modern, Paper & Ink) and 6 animation styles (dramatic, techy, playful, professional, calm, editorial). Includes optional inline editing mode. Saves generated HTML to both <code>./output</code> and <code>./reports</code> folders. Persists files to LangGraph state.</td>
  </tr>
  <tr>
    <td><code>frontend-slides-export-pdf</code></td>
    <td>Exports an HTML presentation to PDF format using Playwright. Calls <code>scripts/export-pdf.sh</code> which captures screenshots of each slide and compiles them into a single PDF document. Note: animations are not preserved in PDF output. Supports compact mode (1280x720 instead of 1920x1080) for smaller file sizes. Requires Playwright installation.</td>
  </tr>
  <tr>
    <td><code>frontend-slides-deploy</code></td>
    <td>Deploys an HTML presentation to a live Vercel URL using the Vercel CLI. Calls <code>scripts/deploy.sh</code> which requires Vercel CLI installation and authentication. Provides shareable public links for presentations.</td>
  </tr>
  <tr>
    <td><code>frontend-slides-extract-pptx</code></td>
    <td>Extracts content and images from PowerPoint (.pptx) files. Runs <code>scripts/extract-pptx.py</code> which returns JSON structures containing slides, text, and embedded images. Facilitates conversion of existing presentations to HTML format. Outputs extracted data to a specified directory for further processing.</td>
  </tr>
</table>

## 🛡️ Rate Limit Handling

### Overview

Model API calls have rate limits that can cause report generation to fail. The deep research agent includes an **automatic retry mechanism with exponential backoff** that gracefully handles rate limit errors from any model provider (OpenAI, Anthropic, Google, Azure, Ollama).

### How It Works

1. **Automatic Detection**: Rate limit errors are automatically detected (429 errors, "too many requests", quota exceeded, etc.)
2. **Exponential Backoff**: When a rate limit is hit, the system waits before retrying:
   - First retry: ~1 second wait
   - Second retry: ~2 seconds wait  
   - Third retry: ~4 seconds wait
   - Fourth retry: ~8 seconds wait
   - Fifth retry: ~16 seconds wait
   - (capped at maximum backoff of 60 seconds)
3. **Jitter**: Random variation (±50%) is added to prevent "thundering herd" when multiple clients retry simultaneously
4. **Maximum Retries**: By default, retries up to 5 times before giving up
5. **Smart Filtering**: Content filter errors (Azure) are NOT retried as they won't succeed on retry

### Configuration

All retry behavior is configurable via environment variables in your `.env` file:

```properties
# Maximum number of retry attempts when rate limit errors occur
MODEL_MAX_RETRIES=5
# Initial backoff time in seconds before first retry
MODEL_INITIAL_BACKOFF=1.0
# Maximum backoff time in seconds (cap for exponential backoff)
MODEL_MAX_BACKOFF=60.0
# Multiplier for exponential backoff (backoff = initial * multiplier^attempt)
MODEL_BACKOFF_MULTIPLIER=2.0
# Add jitter to prevent thundering herd problem (true/false)
MODEL_RETRY_JITTER=true
```

### Tuning Recommendations

#### For Strict Rate Limits (e.g., free tier APIs)
```bash
MODEL_MAX_RETRIES=10
MODEL_INITIAL_BACKOFF=2.0
MODEL_MAX_BACKOFF=120.0
MODEL_BACKOFF_MULTIPLIER=2.0
```

#### For Lenient Rate Limits (e.g., paid tiers)
```bash
MODEL_MAX_RETRIES=3
MODEL_INITIAL_BACKOFF=0.5
MODEL_MAX_BACKOFF=30.0
MODEL_BACKOFF_MULTIPLIER=1.5
```

#### For Local Models (Ollama)
```bash
MODEL_MAX_RETRIES=2
MODEL_INITIAL_BACKOFF=0.5
MODEL_MAX_BACKOFF=10.0
MODEL_BACKOFF_MULTIPLIER=1.5
```

### What Gets Retried

The retry wrapper is automatically applied to all model invocations (`model.invoke()` and `model.ainvoke()`) across all agents in this project.

### Error Messages You'll See

When rate limits are hit, you'll see warning messages like:
```
WARNING:retry_utils:Rate limit hit in invoke (attempt 1/6). Retrying in 1.23s... Error: Rate limit exceeded: 429 Too Many Requests
```

If all retries are exhausted:
```
ERROR:retry_utils:Rate limit error persisted after 5 retries in invoke. Last error: Rate limit exceeded
```

### Troubleshooting

#### Still Getting Failures?

1. **Increase max retries**: Set `MODEL_MAX_RETRIES=10` or higher
2. **Increase initial backoff**: Set `MODEL_INITIAL_BACKOFF=5.0` to start with longer waits
3. **Check your API quota**: You may need to upgrade your plan
4. **Review logs**: Check which specific error is occurring

#### Retries Taking Too Long?

1. **Reduce max retries**: Set `MODEL_MAX_RETRIES=2`
2. **Reduce backoff multiplier**: Set `MODEL_BACKOFF_MULTIPLIER=1.5`
3. **Disable jitter**: Set `MODEL_RETRY_JITTER=false`

#### Want to Disable Retries?

Set `MODEL_MAX_RETRIES=0` in your `.env` file.

### Verification

You can verify the retry mechanism is working correctly by running:

```bash
python tests/test_retry_utils.py
```

This will run a series of verification tests to ensure rate limit detection, backoff calculation, and retry logic are functioning properly.

To run with pytest instead:
```bash
pytest tests/test_retry_utils.py -v
```

---

## 📊 Golden Dataset Evaluation & Regression Tracking

### Overview

The golden-dataset skill now includes comprehensive evaluation tracking to monitor quality, efficiency, and regressions across model updates. Each run is logged as a JSONL record with rich metrics, enabling comparison between baseline and candidate implementations.

### Key Metrics Tracked

#### Test Pass Rate (Completeness)
| Metric | Description                                                                                                                                             |
|--------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| `completeness.pass` | Boolean flag: for the `golden-dataset` skill, `/golden_dataset_metrics.md` and `/final_report.md` are generated in the LangGraph state `files` sandbox. Percentage of code produced by the agent that passes automated tests if the `code-generator` skill is used. |
| `completeness.has_golden_dataset_metrics_md` | Whether the quality metrics report was generated.                                                                                                       |
| `completeness.has_final_report_md` | Whether the final report was generated.                                                                                                                 |

#### Success Rate of Tool Execution
| Metric | Description |
|--------|-------------|
| `tool_execution.total_tool_calls` | Total number of tool invocations across the entire run. |
| `tool_execution.successful_tool_calls` | Count of tool calls that returned valid responses. |
| `tool_execution.failed_tool_calls` | Count of tool calls that failed or returned error content. |
| `tool_execution.success_rate` | Reliability of the agent in using tools (e.g., search, file editing) correctly. If the number of tool calls significantly increases, it should be considered a failure. Ratio of successful to total tool calls. (1.0 if no calls made) |

#### Error Rate/Failure Rate
| Metric | Description |
|--------|-------------|
| `failure.intervention_required` | Boolean. True if completeness failed, stream fallback was used, or tool failure rate > 0. Frequency of failures requiring human intervention. |
| `failure.failure_rate` | Ratio: 1.0 if intervention needed, 0.0 otherwise. |

#### Token Efficiency/Cost Per Task
| Metric | Description |
|--------|-------------|
| `token_efficiency.available` | Boolean. Whether token usage metadata was captured. |
| `token_efficiency.prompt_tokens` | Total input tokens across all messages. |
| `token_efficiency.completion_tokens` | Total output tokens across all messages. |
| `token_efficiency.total_tokens` | Sum of prompt and completion tokens. Monitoring the cost effectiveness of the orchestration. |
| `token_efficiency.tokens_per_successful_task` | Aggregate token count if completeness passed, else null. |

#### Latency
| Metric | Description |
|--------|-------------|
| `latency.runtime_seconds` | End-to-end execution time in seconds. Time taken to complete a complex task. |
| `latency.p50_seconds` | Median latency (currently = runtime for single runs; p50/p95 aggregated across rolling history). |
| `latency.p95_seconds` | 95th percentile latency (currently = runtime; will improve with multi-run analysis). |

### Run Record Structure

Each JSONL entry contains:
```json
{
  "timestamp_utc": "2026-04-23T10:15:30.123456+00:00",
  "run_type": "baseline",
  "manifest": {
    "subject": "Generate 10 question-answer pairs...",
    "skill": "golden-dataset",
    "doc_folder": "./docs/policy",
    "no_web": false,
    "model_name": "claude-sonnet-4-5-20250929",
    "verify_ssl": "True"
  },
  "manifest_hash": "a1b2c3d4e5f6g7h8...",
  "model_name": "claude-sonnet-4-5-20250929",
  "git_sha": "abc1234",
  "runtime_seconds": 45.2,
  "stream_fallback_used": false,
  "output_file": "./output/bmo_policy_qa_pairs-2026-04-23_10_15_30.md",
  "metrics": { /* as detailed above */ }
}
```

### Manifest & Comparison Logic

**Manifest Hash**: Canonical SHA256 hash of the test case (subject, skill, doc_folder, model, etc.). Used for **same-input comparisons only**.

**Critical Design**:
- `"Generate 5 pairs..."` vs `"Generate 10 pairs..."` are **non-comparable** (different manifest hashes).
- Only runs with identical manifests are compared.
- Prevents false regressions when comparing different test cases.

### Usage: Create Baseline & Evaluate Candidate

#### Step 1: Record a Baseline
```bash
uv run python research_agent_cli.py \
  "Generate 5 question-answer pairs for the documents provided" \
  --doc-folder ./docs/policy/ \
  --skill golden-dataset \
  --eval-golden-dataset \
  --eval-mode baseline
```

Output: JSONL entry appended to `./output/eval_history/golden_dataset_runs.jsonl`

#### Step 2: Run a Candidate (Same Input)
```bash
uv run python research_agent_cli.py \
  "Generate 5 question-answer pairs for the documents provided" \
  --doc-folder ./docs/policy/ \
  --skill golden-dataset \
  --eval-golden-dataset \
  --eval-mode candidate
```

**Comparison Output**:
- Fetches latest baseline with matching manifest hash.
- Computes per-metric verdicts: `better`, `same`, `worse`, or `unavailable`.
- Logs verdict summary to stdout.
- Overall verdict combines all metrics:
  - `better` if any metric improved and none regressed.
  - `worse` if any metric degraded (e.g., completeness dropped, failure rate increased, tool calls > baseline * 1.30).
  - `same` if no significant change.

#### Step 3: Custom History File
```bash
uv run python research_agent_cli.py \
  "Generate 5 question-answer pairs for the documents provided" \
  --doc-folder ./docs/policy/ \
  --skill golden-dataset \
  --eval-golden-dataset \
  --eval-history-file ./output/my_eval_runs.jsonl
```

### Regression Thresholds (Built-In)

| Metric | Threshold | Condition |
|--------|-----------|-----------|
| **Tool Growth** | 30% | Candidate tool_calls > baseline * 1.30 → **worse** |
| **Token Efficiency** | 20% | Candidate total_tokens > baseline * 1.20 → **worse** |
| **Latency** | 15% | Candidate p95_seconds > baseline * 1.15 → **worse** |

### Programmatic Access

```python
from research_agent.utils.eval_tracking import (
    build_manifest,
    collect_run_metrics,
    make_run_record,
    append_jsonl,
    load_jsonl,
    latest_baseline,
    compare_records,
)

# Build manifest
manifest = build_manifest(
    subject="Generate 5 pairs",
    skill="golden-dataset",
    doc_folder="./docs/policy",
    no_web=False,
    model_name="claude-sonnet-4-5-20250929",
    verify_ssl=True,
)

# Collect metrics from a run result
metrics = collect_run_metrics(
    result={"messages": [...], "files": {...}},
    runtime_seconds=45.2,
    stream_fallback_used=False,
)

# Create run record
record = make_run_record(
    manifest=manifest,
    run_type="candidate",
    metrics=metrics,
    runtime_seconds=45.2,
    model_name="claude-sonnet-4-5-20250929",
    stream_fallback_used=False,
    output_file="./output/run.md",
    git_sha="abc1234",
)

# Append to history
history_path = Path("./output/eval_history/runs.jsonl")
append_jsonl(history_path, record)

# Load and compare
records = load_jsonl(history_path)
baseline = latest_baseline(records, manifest_hash=record["manifest_hash"])
comparison = compare_records(baseline=baseline, candidate=record)
print(f"Overall verdict: {comparison['overall_verdict']}")
print(f"Per-metric: {comparison['per_metric']}")
```

### Testing

Run the evaluation tracking tests:
```bash
pytest tests/test_eval_tracking.py -v
```

Tests verify:
- Manifest hash stability and change detection.
- Completeness gating (both artifacts required).
- Tool-call success/failure parsing.
- Baseline selection (latest matching manifest).
- Non-comparable manifest mismatches.
- JSONL append and reload integrity.