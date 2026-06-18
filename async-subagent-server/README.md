# Async Subagent Server

A self-hosted [Agent Protocol](https://github.com/langchain-ai/agent-protocol) server that exposes a DeepAgents
researcher as an async subagent. Use this as a starting point for hosting your own agent on any infrastructure and
connecting it to a DeepAgents supervisor.

The example includes both sides of the pattern:

- **`server.py`** — the FastAPI server your subagent runs on
- **`supervisor.py`** — an interactive REPL showing how to connect to it

## Prerequisites

- `ANTHROPIC_API_KEY` — required
- `TAVILY_API_KEY` — optional; stub search is used if not set

## Quickstart

**1. Install dependencies:**

```bash
cd async-subagent-server
uv sync
```

**2. Set up your environment:**

```bash
cp .env.example .env
# fill in your model provider variables and optionally TAVILY_API_KEY
```

**3. Start the server:**

```bash
uv run uvicorn server:app --port 2024
```

**4. In another terminal, start the supervisor:**

```bash
cd async-subagent-server
uv run python supervisor.py
```

Try these prompts:

```
> research the latest developments in quantum computing
> check status of <task-id>
> update <task-id> to focus on commercial applications only
> cancel <task-id>
> list all tasks
```

## Implemented endpoints

These are the Agent Protocol endpoints the DeepAgents async subagent middleware calls (via the LangGraph SDK):

| Endpoint                                         | Purpose                                |
|--------------------------------------------------|----------------------------------------|
| `POST /threads`                                  | Create a thread for a new task         |
| `POST /threads/{thread_id}/runs`                 | Start or interrupt+restart a run       |
| `GET /threads/{thread_id}/runs/{run_id}`         | Poll run status                        |
| `GET /threads/{thread_id}`                       | Fetch thread state (`values.messages`) |
| `POST /threads/{thread_id}/runs/{run_id}/cancel` | Cancel a run                           |
| `GET /ok`                                        | Health check                           |

## Swap in your own agent

Replace the `create_deep_agent` call in `server.py` with your own agent. The Agent Protocol layer stays the same
regardless of what the agent does.

```python
_agent = create_deep_agent(
    model=ChatAnthropic(model="claude-sonnet-4-5"),
    system_prompt="You are a ...",
    tools=[your_tool],
)
```

## Model configuration in this repo

This workspace keeps the upstream async-subagent example behavior, but the supervisor uses `model_factory.py`
instead of hardcoding Anthropic. `model_factory.py` selects the first configured provider from this order:

- AWS Bedrock-compatible endpoint via `AWS_BEDROCK_ENDPOINT`, `AWS_BEARER_TOKEN_BEDROCK`, `MODEL_NAME`
- Azure OpenAI via `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`
- Google via `GOOGLE_API_KEY`, `MODEL_NAME`
- Anthropic via `ANTHROPIC_API_KEY`, `MODEL_NAME`
- Ollama via `OLLAMA_API_BASE`, `MODEL_NAME`

The FastAPI server in `server.py` still uses the example's built-in researcher agent wiring. Keep that contract intact
when merging newer upstream changes.

## ⚠️ For demonstration purposes only

This example is intended to illustrate the self-hosted async subagent pattern. It does not feature authentication, rate
limiting, or other features required for production use.
