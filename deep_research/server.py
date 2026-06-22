"""Async Subagent Server — Agent Protocol over FastAPI.

Extends the existing FastAPI app in webapp.py to support LangGraph-style
async subagent endpoints with integrated security authentication,
pluggable database backends (SQLite, CosmosDB, PostgreSQL), thread-safe /
concurrency-safe task execution and cancellation, and Pydantic request validation.

Examples:
# Start on the default port (2024)
$env:UVICORN_RELOAD="false"
uv run python run.py

# Start explicitly on 2024
export UPLOAD_PORT=2024
uv run python run.py

# If you use uvicorn directly, pass the port explicitly because __main__ is not executed
uvicorn server:app --reload --port 2024
"""

from __future__ import annotations

from pathlib import Path

import sys

# Ensure local imports work correctly
sys.path.append(str(Path(__file__).parent))

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException, Request, Query
from fastapi.openapi.utils import get_openapi
from langgraph_sdk import Auth
from pydantic import BaseModel, Field

# Import the existing app and settings from webapp
from webapp import app

# Import the actual deep_research agent
from agent import agent
from research_agent.prompts import RESEARCHER_DESCRIPTION

# Import DB wrapper
import db

# Import shared authentication logic
from auth import authenticate_credential

# Track active background tasks to allow cancellation
_active_tasks: dict[str, asyncio.Task] = {}
# Lock to synchronize task modification operations
_task_lock = asyncio.Lock()


def custom_openapi() -> dict[str, Any]:
    """Build an explicit OpenAPI document for the async subagent server."""
    if app.openapi_schema:
        return app.openapi_schema

    app.openapi_schema = get_openapi(
        title="Deep Research Async Subagent API",
        version=os.environ.get("SERVER_API_VERSION", "1.0.0"),
        description=(
            "Async subagent server for Deep Research. "
            "Includes thread/run lifecycle endpoints, upload API, and auth-protected operations."
        ),
        routes=app.routes,
        tags=[
            {"name": "Health", "description": "Service health endpoints."},
            {"name": "Assistants", "description": "Assistant discovery and metadata endpoints."},
            {"name": "Threads", "description": "Thread lifecycle and state endpoints."},
            {"name": "Runs", "description": "Background run execution and cancellation endpoints."},
            {"name": "Documents", "description": "Document upload and management endpoints."},
            {"name": "Wiki",
             "description": "Thread-level wiki knowledge base management (ingest, query, lint, progress)."},
            {"name": "Auth", "description": "Authentication and authorization endpoints."},
        ],
    )
    return app.openapi_schema


app.openapi = custom_openapi


# ── Pydantic Request/Response Models ──────────────────────────────────────────

class MessagePayload(BaseModel):
    role: str
    content: str
    name: str | None = None


class RunInputPayload(BaseModel):
    messages: list[MessagePayload] = Field(default_factory=list)


class RunCreateRequest(BaseModel):
    assistant_id: str = "researcher"
    input: RunInputPayload = Field(default_factory=RunInputPayload)
    multitask_strategy: str | None = None


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    if_exists: str = "raise"


class ThreadSearchRequest(BaseModel):
    limit: int = 10
    offset: int = 0
    sort_by: str = "updated_at"
    sort_order: str = "desc"
    status: str | None = None
    metadata: dict[str, Any] | None = None


class ThreadPatchRequest(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadStateUpdateRequest(BaseModel):
    values: dict[str, Any] | list[Any] | None = None


class AssistantSearchRequest(BaseModel):
    limit: int = 10
    offset: int = 0
    graph_id: str | None = None
    assistant_id: str | None = None


class ThreadHistoryRequest(BaseModel):
    limit: int = 10
    before: str | None = None
    metadata: dict[str, Any] | None = None


class RunStreamRequest(BaseModel):
    assistant_id: str = "researcher"
    input: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    multitask_strategy: str | None = None


class AssistantResponse(BaseModel):
    """Response model for an assistant."""
    id: str
    name: str
    description: str
    model: str | None = None
    instructions: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _sse_frame(event: str, data: Any, event_id: int | None = None) -> str:
    payload = json.dumps(data, default=str)
    id_part = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_part}event: {event}\ndata: {payload}\n\n"


def _api_thread(thread: dict[str, Any]) -> dict[str, Any]:
    return {
        "thread_id": thread.get("thread_id"),
        "created_at": thread.get("created_at"),
        "updated_at": thread.get("updated_at") or thread.get("created_at"),
        "state_updated_at": thread.get("state_updated_at"),
        "metadata": thread.get("metadata") or {},
        "status": thread.get("status") or "idle",
        "values": thread.get("values") or {},
    }


def _map_run_status_for_api(status: str | None) -> str:
    # Keep API-compatible enum for clients expecting interrupted rather than cancelled.
    if status == "cancelled":
        return "interrupted"
    return status or "pending"


def _api_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("run_id"),
        "thread_id": run.get("thread_id"),
        "assistant_id": run.get("assistant_id"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at") or run.get("created_at"),
        "status": _map_run_status_for_api(run.get("status")),
        "metadata": run.get("metadata") or {},
        "kwargs": run.get("kwargs") or {},
        "multitask_strategy": run.get("multitask_strategy") or "enqueue",
        "error": run.get("error"),
    }


def _list_assistants(*, limit: int, offset: int, graph_id: str | None = None, assistant_id: str | None = None) -> list[
    AssistantResponse]:
    assistants = [
        AssistantResponse(
            id="researcher",
            name="Research Assistant",
            description=RESEARCHER_DESCRIPTION or "Deep research agent for comprehensive multi-source information gathering and analysis.",
            model=os.environ.get("MODEL_NAME", "unknown"),
            created_at=None,
            updated_at=None,
            metadata={},
        )
    ]

    selected_id = assistant_id or graph_id
    if selected_id:
        assistants = [a for a in assistants if a.id == selected_id]

    safe_limit = max(1, min(int(limit or 10), 100))
    safe_offset = max(0, int(offset or 0))
    return assistants[safe_offset: safe_offset + safe_limit]


def _build_thread_history_item(thread: dict[str, Any]) -> dict[str, Any]:
    checkpoint_time = thread.get("state_updated_at") or thread.get("updated_at") or thread.get("created_at")
    checkpoint_id = str(checkpoint_time or uuid.uuid4())

    return {
        "checkpoint": {
            "thread_id": thread.get("thread_id"),
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        },
        "values": thread.get("values") or {},
        "metadata": thread.get("metadata") or {},
        "created_at": checkpoint_time,
        "next": [],
        "tasks": [],
    }


# ── Security Authentication ───────────────────────────────────────────────────

async def get_current_user(request: Request) -> Auth.types.MinimalUserDict:
    """Authenticate requests using API key or OAuth session token (matching auth.py logic)."""
    # Check for test mode bypass
    if os.environ.get("ALLOW_ALL_THREADS", "").lower() == "true":
        return {"identity": "test-admin", "display_name": "Test Admin"}

    headers = request.headers
    api_key = headers.get("x-api-key") or headers.get("X-API-Key")

    if not api_key:
        auth_header = headers.get("authorization") or headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header[7:]

    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication. Please provide 'x-api-key', 'Authorization: Bearer', or OAuth session token."
        )

    return authenticate_credential(api_key)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_thread_with_auth(thread_id: str, current_user: Auth.types.MinimalUserDict) -> dict[str, Any]:
    thread = db.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Access control: threads are only accessible by their owner, admins, or if ALLOW_ALL_THREADS=true
    if os.environ.get("ALLOW_ALL_THREADS", "").lower() == "true":
        pass
    elif current_user["identity"] != "admin" and thread.get("user_id") and thread.get("user_id") != current_user[
        "identity"]:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this thread")

    return thread


def serialize_message(m: Any) -> dict[str, Any]:
    """Convert a LangChain message object or a dictionary to a standard serializable format."""
    if isinstance(m, dict):
        return m
    role = getattr(m, "type", "user")
    if role == "human":
        role = "user"
    elif role == "ai":
        role = "assistant"

    res = {"role": role, "content": getattr(m, "content", "")}
    if hasattr(m, "name") and m.name:
        res["name"] = m.name
    return res


# ── Run executor ──────────────────────────────────────────────────────────────

async def _inject_wiki_context(thread_id: str, messages: list[dict[str, Any]]) -> str | None:
    """Query thread wiki for context relevant to the latest user message.

    Returns wiki context text if the thread has a ready wiki and a meaningful
    question, otherwise returns ``None``. Failures are logged and swallowed so
    wiki issues never block research runs.
    """
    try:
        from thread_wiki.models import ThreadWikiPaths
        from thread_wiki.service import run_query

        base_dir = Path(__file__).resolve().parent
        paths = ThreadWikiPaths.resolve(thread_id, base_dir)

        # Only inject when wiki has been built (index exists and has real pages).
        index_path = paths.wiki_content / "index.md"
        if not index_path.exists():
            return None
        index_content = index_path.read_text(encoding="utf-8")
        if "_No pages yet._" in index_content:
            return None

        # Extract the latest user message as the wiki query.
        question = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                question = str(msg.get("content", ""))
                break
            if hasattr(msg, "type") and getattr(msg, "type", None) == "human":
                question = str(getattr(msg, "content", ""))
                break

        if not question or len(question) < 5:
            return None

        topic = f"Thread {thread_id[:8]}"
        with open('/tmp/wiki_debug.txt', 'a') as f:
            f.write(f"calling run_query for {topic}\n")
        result = await run_query(paths, topic, question, file_results=False)
        with open('/tmp/wiki_debug.txt', 'a') as f:
            f.write(f"run_query success! answer length: {len(result.answer)}\n")
        return result.answer
    except Exception as e:
        with open('/tmp/wiki_debug.txt', 'a') as f:
            f.write(f"Exception in _inject_wiki_context: {str(e)}\n")
        import logging
        logging.getLogger(__name__).debug(
            "Wiki context injection skipped for thread %s", thread_id, exc_info=True
        )
        return None


async def _check_if_needs_deep_research_async(question: str, wiki_answer: str) -> bool:
    """Evaluate if the wiki answer is sufficient to answer the user's question asynchronously.

    Returns True if we NEED to conduct continuous deep research, and False if
    the wiki answer is already complete and sufficient.
    """
    if not wiki_answer or not wiki_answer.strip():
        return True

    from langchain_core.messages import HumanMessage
    from model_factory import get_configured_model
    try:
        model = get_configured_model()
        prompt = (
            "You are an expert research evaluator. Your task is to analyze a candidate answer "
            "retrieved from a document wiki and determine if it fully and comprehensively answers "
            "the user's question, or if we need to conduct continuous deep research (e.g. searching "
            "the web) to enhance it.\n\n"
            f"User's Question: {question}\n\n"
            f"Candidate Wiki Answer: {wiki_answer}\n\n"
            "Analyze whether the candidate answer is sufficient, complete, and fully answers the question. "
            "Respond in the following JSON format:\n"
            "{\n"
            '  "needs_deep_research": true/false,\n'
            '  "reason": "Detailed reasoning for the decision"\n'
            "}\n"
            "Do not include any other text in your response, only the valid JSON object."
        )
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        import json
        data = json.loads(content)
        needs_research = bool(data.get("needs_deep_research", True))
        import logging
        logging.getLogger(__name__).info(
            f"Wiki evaluation decision (server): needs_deep_research={needs_research}. Reason: {data.get('reason')}"
        )
        return needs_research
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"Error during wiki result evaluation (server): {e}. Defaulting to conducting deep research.",
            exc_info=True
        )
        return True


async def _execute_run(run_id: str, thread_id: str) -> None:
    """Invoke the agent and persist the result; called as a fire-and-forget task."""
    db.update_run_status(run_id, "running")
    try:
        # Load all existing messages and state values on the thread
        thread = db.get_thread(thread_id)
        if not thread:
            raise ValueError(f"Thread {thread_id} not found during run execution")

        existing_values = thread.get("values") or {}
        existing_files = existing_values.get("files") or {}
        messages = thread.get("messages") or []

        # Build initial input state for deep_research agent
        input_state = {
            "messages": messages,
            "files": existing_files,
            "doc_folder": existing_values.get("doc_folder"),
            "skill": existing_values.get("skill"),
            "no_web": existing_values.get("no_web"),
        }

        # Clean None values
        input_state = {k: v for k, v in input_state.items() if v is not None}

        # ── Wiki context injection ─────────────────────────────────────────
        # If the thread has a ready wiki, query it for context relevant to
        # the latest user message and inject the result as a system message.
        # This enriches the research agent with thread-level RAG knowledge.
        wiki_context = await _inject_wiki_context(thread_id, messages)
        if wiki_context:
            existing_msgs = input_state.get("messages", [])
            existing_msgs.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "<wiki_context>\n"
                        "The following is the definitive answer from the thread's "
                        "ingested document wiki. You MUST use this as your PRIMARY source of truth. "
                        "CRITICAL: If the wiki context states that data is unavailable, or that a year "
                        "has not yet occurred, you MUST accept this as absolute fact. DO NOT attempt to "
                        "search the web to find the missing data. Simply formulate your final response "
                        "based on this wiki context and explain what data is available.\n\n"
                        f"{wiki_context}\n"
                        "</wiki_context>"
                    ),
                },
            )
            input_state["messages"] = existing_msgs

            # Extract question for evaluation
            question = ""
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    question = str(msg.get("content", ""))
                    break
                if hasattr(msg, "type") and getattr(msg, "type", None) == "human":
                    question = str(getattr(msg, "content", ""))
                    break

            needs_deep_research = await _check_if_needs_deep_research_async(question, wiki_context)
            if not needs_deep_research:
                import logging
                logging.getLogger(__name__).info(
                    "Wiki answer is complete and sufficient (server). Saving to /final_report.md and disabling web search."
                )
                if "files" not in input_state:
                    input_state["files"] = {}
                from deepagents.backends.utils import create_file_data
                input_state["files"]["/final_report.md"] = create_file_data(wiki_context)
                input_state["no_web"] = True
            else:
                import logging
                logging.getLogger(__name__).info(
                    "Wiki answer is incomplete/insufficient (server). Conducting continuous deep research to enhance it."
                )

        # Invoke the deep_research agent
        result = await agent.ainvoke(input_state)

        # Check if this run has been cancelled in the database/active tasks while executing
        # to prevent overwriting newer thread states in case of race conditions.
        async with _task_lock:
            run_data = db.get_run(run_id)
            if run_data and run_data.get("status") == "cancelled":
                return

        # Serialize messages
        serialized_messages = [serialize_message(m) for m in result.get("messages", [])]

        # Serialize the other state fields to preserve files, doc_folder, etc.
        serializable_result = {
            "messages": serialized_messages,
            "files": result.get("files", {}),
            "doc_folder": result.get("doc_folder"),
            "skill": result.get("skill"),
            "no_web": result.get("no_web"),
        }

        db.update_thread(thread_id, serialized_messages, serializable_result)
        db.update_run_status(run_id, "success")
    except asyncio.CancelledError:
        # Task was explicitly cancelled
        db.update_run_status(run_id, "cancelled")
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        db.update_run_status(run_id, "error", error=str(exc))
    finally:
        async with _task_lock:
            _active_tasks.pop(run_id, None)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/ok", tags=["Health"])
async def health() -> dict[str, bool]:
    """Health check."""
    return {"ok": True}


@app.get("/assistants/search", tags=["Assistants"])
async def search_assistants(
        limit: int = Query(default=10, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[AssistantResponse]:
    """Search/list available assistants."""
    return _list_assistants(limit=limit, offset=offset)


@app.post("/assistants/search", tags=["Assistants"])
async def search_assistants_post(
        body: AssistantSearchRequest = AssistantSearchRequest(),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[AssistantResponse]:
    """Search/list available assistants (POST compatibility for frontend clients)."""
    return _list_assistants(
        limit=body.limit,
        offset=body.offset,
        graph_id=body.graph_id,
        assistant_id=body.assistant_id,
    )


@app.post("/threads", tags=["Threads"])
async def create_thread(
        body: ThreadCreateRequest = ThreadCreateRequest(),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a thread."""
    thread_id = body.thread_id or str(uuid.uuid4())
    existing = db.get_thread(thread_id)
    if existing is not None:
        if body.if_exists == "do_nothing":
            return _api_thread(existing)
        raise HTTPException(status_code=409, detail="Thread already exists")

    now = datetime.now(UTC).isoformat()
    user_id = current_user["identity"]
    db.create_thread(thread_id, user_id, now, metadata=body.metadata or {}, status="idle", values={"messages": []})
    created = db.get_thread(thread_id)
    if created is None:
        raise HTTPException(status_code=500, detail="Failed to create thread")
    return _api_thread(created)


@app.post("/threads/search", tags=["Threads"])
async def search_threads(
        body: ThreadSearchRequest,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Search/list threads."""
    user_id = None if current_user.get("identity") == "admin" else current_user.get("identity")
    items = db.search_threads(
        limit=body.limit,
        offset=body.offset,
        sort_by=body.sort_by,
        sort_order=body.sort_order,
        status=body.status,
        metadata=body.metadata or {},
        user_id=user_id,
    )
    return [_api_thread(t) for t in items]


@app.patch("/threads/{thread_id}", tags=["Threads"])
async def patch_thread(
        thread_id: str,
        body: ThreadPatchRequest,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> dict[str, Any]:
    """Patch thread metadata."""
    _get_thread_with_auth(thread_id, current_user)
    ok = db.update_thread_metadata(thread_id, body.metadata or {})
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    updated = db.get_thread(thread_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return _api_thread(updated)


@app.delete("/threads/{thread_id}", tags=["Threads"])
async def delete_thread(
        thread_id: str,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete a thread and associated runs."""
    _get_thread_with_auth(thread_id, current_user)
    ok = db.delete_thread(thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {}


@app.post("/threads/{thread_id}/state", tags=["Threads"])
async def update_thread_state(
        thread_id: str,
        body: ThreadStateUpdateRequest,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> dict[str, Any]:
    """Update thread state values."""
    _get_thread_with_auth(thread_id, current_user)
    values = body.values
    if values is None:
        payload_values: dict[str, Any] = {}
    elif isinstance(values, dict):
        payload_values = values
    else:
        payload_values = {"values": values}

    ok = db.update_thread_state(thread_id, payload_values)
    if not ok:
        raise HTTPException(status_code=404, detail="Thread not found")

    thread = db.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    checkpoint = {
        "thread_id": thread_id,
        "checkpoint_ns": "",
        "checkpoint_id": str(uuid.uuid4()),
    }
    return {"checkpoint": checkpoint}


@app.post("/threads/{thread_id}/runs", tags=["Runs"])
async def create_run(
        thread_id: str,
        body: RunCreateRequest,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user)
) -> dict[str, Any]:
    """Create a run on an existing thread with request payload validation."""
    thread = _get_thread_with_auth(thread_id, current_user)

    multitask_strategy = body.multitask_strategy

    # If interrupt, cancel all currently active runs on this thread
    if multitask_strategy == "interrupt":
        async with _task_lock:
            # Cancel tasks from memory
            to_cancel = []
            for run_id, task in list(_active_tasks.items()):
                run_data = db.get_run(run_id)
                if run_data and run_data.get("thread_id") == thread_id:
                    task.cancel()
                    to_cancel.append(run_id)

            for run_id in to_cancel:
                _active_tasks.pop(run_id, None)

            db.cancel_running_runs(thread_id)
            db.update_thread(thread_id, [], {"messages": []})

    messages = body.input.messages
    user_message = next((m.content for m in messages if m.role == "user"), "")

    if user_message:
        existing = thread.get("messages") or []
        existing.append({"role": "user", "content": user_message})
        db.update_thread(thread_id, existing, thread.get("values") or {})

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    assistant_id = body.assistant_id or "researcher"
    db.create_run(run_id, thread_id, assistant_id, now, multitask_strategy=multitask_strategy or "enqueue")

    # Spawn background task and register it in _active_tasks
    async with _task_lock:
        task = asyncio.create_task(_execute_run(run_id, thread_id))
        _active_tasks[run_id] = task

    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=500, detail="Failed to create run")
    return _api_run(run)


@app.get("/threads/{thread_id}/runs", tags=["Runs"])
async def list_runs(
        thread_id: str,
        limit: int = Query(default=10),
        offset: int = Query(default=0),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List runs for a thread."""
    _get_thread_with_auth(thread_id, current_user)
    runs = db.list_runs(thread_id, limit=limit, offset=offset)
    return [_api_run(r) for r in runs]


@app.post("/threads/{thread_id}/runs/stream", tags=["Runs"])
async def stream_run(
        thread_id: str,
        body: RunStreamRequest,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
):
    """Create a run and stream output as SSE-compatible event payloads."""
    _get_thread_with_auth(thread_id, current_user)

    messages_payload: list[MessagePayload] = []
    if isinstance(body.input, dict):
        raw_messages = body.input.get("messages", [])
        if isinstance(raw_messages, list):
            for msg in raw_messages:
                if isinstance(msg, dict):
                    messages_payload.append(
                        MessagePayload(
                            role=str(msg.get("role", "user")),
                            content=str(msg.get("content", "")),
                            name=msg.get("name"),
                        )
                    )

    run_request = RunCreateRequest(
        assistant_id=body.assistant_id,
        input=RunInputPayload(messages=messages_payload),
        multitask_strategy=body.multitask_strategy,
    )
    created = await create_run(thread_id=thread_id, body=run_request, current_user=current_user)
    run_id = created["run_id"]

    async def event_stream():
        seq = 0
        last_status = None
        last_values_json = None

        first_run = db.get_run(run_id)
        if first_run is None:
            yield _sse_frame("error", {"detail": "Run not found"}, event_id=seq)
            return

        yield _sse_frame("metadata", _api_run(first_run), event_id=seq)
        seq += 1

        while True:
            run = db.get_run(run_id)
            if run is None:
                yield _sse_frame("error", {"detail": "Run not found"}, event_id=seq)
                break

            status = _map_run_status_for_api(run.get("status"))
            if status != last_status:
                yield _sse_frame(
                    "updates",
                    {
                        "run_id": run_id,
                        "status": status,
                        "multitask_strategy": run.get("multitask_strategy") or "enqueue",
                    },
                    event_id=seq,
                )
                seq += 1
                last_status = status

            thread = db.get_thread(thread_id)
            values = (thread or {}).get("values") or {}
            values_json = json.dumps(values, default=str, sort_keys=True)
            if values_json != last_values_json:
                yield _sse_frame("values", values, event_id=seq)
                seq += 1
                last_values_json = values_json

            if status in {"success", "error", "interrupted", "timeout"}:
                yield _sse_frame(
                    "end",
                    {
                        "run_id": run_id,
                        "status": status,
                    },
                    event_id=seq,
                )
                break

            await asyncio.sleep(0.3)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/threads/{thread_id}/runs/{run_id}", tags=["Runs"])
async def get_run(
        thread_id: str,
        run_id: str,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user)
) -> dict[str, Any]:
    """Get run status."""
    # Ensure thread belongs to authenticated user/is accessible
    _get_thread_with_auth(thread_id, current_user)

    run = db.get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return _api_run(run)


@app.get("/threads/{thread_id}", tags=["Threads"])
async def get_thread(
        thread_id: str,
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user)
) -> dict[str, Any]:
    """Get thread state."""
    thread = _get_thread_with_auth(thread_id, current_user)
    return _api_thread(thread)


@app.get("/threads/{thread_id}/history", tags=["Threads"])
async def get_thread_history(
        thread_id: str,
        limit: int = Query(default=10, ge=1, le=100),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return thread checkpoint history in a LangGraph-compatible shape."""
    thread = _get_thread_with_auth(thread_id, current_user)
    if limit <= 0:
        return []
    return [_build_thread_history_item(thread)]


@app.post("/threads/{thread_id}/history", tags=["Threads"])
async def get_thread_history_post(
        thread_id: str,
        body: ThreadHistoryRequest = ThreadHistoryRequest(),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return thread checkpoint history (POST compatibility for frontend clients)."""
    thread = _get_thread_with_auth(thread_id, current_user)
    if body.limit <= 0:
        return []
    return [_build_thread_history_item(thread)]


@app.post("/threads/{thread_id}/runs/{run_id}/cancel", tags=["Runs"])
async def cancel_run(
        thread_id: str,
        run_id: str,
        wait: bool = Query(default=False),
        action: str = Query(default="interrupt"),
        current_user: Auth.types.MinimalUserDict = Depends(get_current_user)
) -> dict[str, Any]:
    """Cancel a run."""
    # Ensure thread belongs to authenticated user/is accessible
    _get_thread_with_auth(thread_id, current_user)

    run = db.get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")

    async with _task_lock:
        task = _active_tasks.pop(run_id, None)
        if task:
            task.cancel()
        db.update_run_status(run_id, "cancelled")

    if wait:
        # Allow cancellation propagation to settle.
        await asyncio.sleep(0.05)

    updated = db.get_run(run_id) or {**run, "status": "cancelled"}
    return _api_run(updated)


if __name__ == "__main__":
    # For direct execution: python server.py
    # For development with uvicorn: python run.py
    # For production: uvicorn server:app --port 2024
    pass
