"""Async Subagent Server — Agent Protocol over FastAPI.

Extends the existing FastAPI app in webapp.py to support LangGraph-style
async subagent endpoints with integrated security authentication,
pluggable database backends (SQLite, CosmosDB, PostgreSQL), thread-safe /
concurrency-safe task execution and cancellation, and Pydantic request validation.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure local imports work correctly
sys.path.append(str(Path(__file__).parent))

import asyncio
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field

# Import the existing app and settings from webapp
from webapp import app

# Import the actual deep_research agent
from agent import agent

# Import DB wrapper
import db

# Track active background tasks to allow cancellation
_active_tasks: dict[str, asyncio.Task] = {}
# Lock to synchronize task modification operations
_task_lock = asyncio.Lock()


@app.on_event("startup")
async def startup_event():
    db.init_db()


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


# ── Security Authentication ───────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict[str, Any]:
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

    # Try to validate as OAuth session token
    from oauth_handler import user_manager
    user_data = user_manager.validate_session(api_key)
    if user_data:
        return {
            "identity": user_data["identity"],
            "display_name": user_data.get("name", user_data["identity"]),
        }

    # API key authentication
    expected_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("UPLOAD_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="Server configuration error: LANGCHAIN_API_KEY not set."
        )

    if api_key != expected_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key or session token."
        )

    return {
        "identity": "admin",
        "display_name": "Admin",
    }


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_thread_with_auth(thread_id: str, current_user: dict[str, Any]) -> dict[str, Any]:
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

@app.get("/ok")
async def health() -> dict[str, bool]:
    """Health check."""
    return {"ok": True}


@app.post("/threads")
async def create_thread(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Create a thread."""
    thread_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    user_id = current_user["identity"]
    db.create_thread(thread_id, user_id, now)
    return {"thread_id": thread_id, "created_at": now, "messages": [], "values": {}, "user_id": user_id}


@app.post("/threads/{thread_id}/runs")
async def create_run(
        thread_id: str,
        body: RunCreateRequest,
        current_user: dict[str, Any] = Depends(get_current_user)
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
            db.update_thread(thread_id, [], {})

    messages = body.input.messages
    user_message = next((m.content for m in messages if m.role == "user"), "")

    if user_message:
        existing = thread.get("messages") or []
        existing.append({"role": "user", "content": user_message})
        db.update_thread(thread_id, existing, thread.get("values") or {})

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    assistant_id = body.assistant_id or "researcher"
    db.create_run(run_id, thread_id, assistant_id, now)

    # Spawn background task and register it in _active_tasks
    async with _task_lock:
        task = asyncio.create_task(_execute_run(run_id, thread_id))
        _active_tasks[run_id] = task

    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "assistant_id": assistant_id,
        "status": "pending",
        "created_at": now,
        "error": None,
    }


@app.get("/threads/{thread_id}/runs/{run_id}")
async def get_run(
        thread_id: str,
        run_id: str,
        current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Get run status."""
    # Ensure thread belongs to authenticated user/is accessible
    _get_thread_with_auth(thread_id, current_user)

    run = db.get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/threads/{thread_id}")
async def get_thread(
        thread_id: str,
        current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Get thread state."""
    return _get_thread_with_auth(thread_id, current_user)


@app.post("/threads/{thread_id}/runs/{run_id}/cancel")
async def cancel_run(
        thread_id: str,
        run_id: str,
        current_user: dict[str, Any] = Depends(get_current_user)
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

    return {**run, "status": "cancelled"}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("UPLOAD_HOST", "0.0.0.0")
    port = int(os.environ.get("UPLOAD_PORT", "8000"))

    print(f"🚀 Starting Document Upload & Agent API Server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
