"""Async Subagent Server — Agent Protocol over FastAPI.

Extends the existing FastAPI app in webapp.py to support LangGraph-style
async subagent endpoints with integrated security authentication.
"""

from __future__ import annotations

import sys
from pathlib import Path
# Ensure local imports work correctly
sys.path.append(str(Path(__file__).parent))

import asyncio
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, HTTPException, Request

# Import the existing app and settings from webapp
from webapp import app

# Import the actual deep_research agent
from agent import agent

# ── Database ──────────────────────────────────────────────────────────────────

# In-memory SQLite shared across all connections in this process.
_conn = sqlite3.connect(":memory:", check_same_thread=False)
_conn.row_factory = sqlite3.Row


def _init_db() -> None:
    """Create the threads and runs tables if they don't already exist."""
    _conn.executescript("""
        CREATE TABLE IF NOT EXISTS threads (
            thread_id  TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            messages   TEXT NOT NULL DEFAULT '[]',
            values_    TEXT NOT NULL DEFAULT '{}',
            user_id    TEXT
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id       TEXT PRIMARY KEY,
            thread_id    TEXT NOT NULL REFERENCES threads(thread_id),
            assistant_id TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            created_at   TEXT NOT NULL,
            error        TEXT
        );
    """)
    _conn.commit()


@app.on_event("startup")
async def startup_event():
    _init_db()


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
    row = _conn.execute(
        "SELECT thread_id, created_at, messages, values_, user_id FROM threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Access control: threads are only accessible by their owner, admins, or if ALLOW_ALL_THREADS=true
    if os.environ.get("ALLOW_ALL_THREADS", "").lower() == "true":
        pass
    elif current_user["identity"] != "admin" and row["user_id"] and row["user_id"] != current_user["identity"]:
        raise HTTPException(status_code=403, detail="Forbidden: You do not own this thread")

    return {
        "thread_id": row["thread_id"],
        "created_at": row["created_at"],
        "messages": json.loads(row["messages"]),
        "values": json.loads(row["values_"]),
        "user_id": row["user_id"],
    }


def _get_run(run_id: str) -> dict[str, Any] | None:
    row = _conn.execute(
        "SELECT run_id, thread_id, assistant_id, status, created_at, error FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


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
    _conn.execute("UPDATE runs SET status = 'running' WHERE run_id = ?", (run_id,))
    _conn.commit()
    try:
        # Load all existing messages and state values on the thread
        row = _conn.execute(
            "SELECT messages, values_ FROM threads WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        
        existing_values = json.loads(row["values_"]) if row and row["values_"] else {}
        existing_files = existing_values.get("files", {})
        messages = json.loads(row["messages"]) if row else []
        
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
        
        _conn.execute(
            "UPDATE threads SET messages = ?, values_ = ? WHERE thread_id = ?",
            (json.dumps(serialized_messages), json.dumps(serializable_result), thread_id),
        )
        _conn.execute("UPDATE runs SET status = 'success' WHERE run_id = ?", (run_id,))
        _conn.commit()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        _conn.execute(
            "UPDATE runs SET status = 'error', error = ? WHERE run_id = ?",
            (str(exc), run_id),
        )
        _conn.commit()


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
    _conn.execute(
        "INSERT INTO threads (thread_id, created_at, user_id) VALUES (?, ?, ?)",
        (thread_id, now, user_id),
    )
    _conn.commit()
    return {"thread_id": thread_id, "created_at": now, "messages": [], "values": {}, "user_id": user_id}


@app.post("/threads/{thread_id}/runs")
async def create_run(
    thread_id: str,
    request: Request,
    current_user: dict[str, Any] = Depends(get_current_user)
) -> dict[str, Any]:
    """Create a run on an existing thread."""
    thread = _get_thread_with_auth(thread_id, current_user)

    body = await request.json()
    multitask_strategy = body.get("multitask_strategy")

    if multitask_strategy == "interrupt":
        _conn.execute(
            "UPDATE runs SET status = 'cancelled' WHERE thread_id = ? AND status = 'running'",
            (thread_id,),
        )
        _conn.execute(
            "UPDATE threads SET values_ = '{}' WHERE thread_id = ?",
            (thread_id,),
        )
        _conn.commit()

    messages = (body.get("input") or {}).get("messages") or []
    user_message = next((m["content"] for m in messages if m.get("role") == "user"), "")

    if user_message:
        existing = json.loads(
            _conn.execute(
                "SELECT messages FROM threads WHERE thread_id = ?", (thread_id,)
            ).fetchone()[0]
        )
        existing.append({"role": "user", "content": user_message})
        _conn.execute(
            "UPDATE threads SET messages = ? WHERE thread_id = ?",
            (json.dumps(existing), thread_id),
        )
        _conn.commit()

    run_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    assistant_id = body.get("assistant_id") or "researcher"
    _conn.execute(
        "INSERT INTO runs (run_id, thread_id, assistant_id, created_at) VALUES (?, ?, ?, ?)",
        (run_id, thread_id, assistant_id, now),
    )
    _conn.commit()

    # Fire and forget run executor
    asyncio.ensure_future(_execute_run(run_id, thread_id))

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
    
    run = _get_run(run_id)
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

    run = _get_run(run_id)
    if run is None or run["thread_id"] != thread_id:
        raise HTTPException(status_code=404, detail="Run not found")
    _conn.execute("UPDATE runs SET status = 'cancelled' WHERE run_id = ?", (run_id,))
    _conn.commit()
    return {**run, "status": "cancelled"}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("UPLOAD_HOST", "0.0.0.0")
    port = int(os.environ.get("UPLOAD_PORT", "8000"))

    print(f"🚀 Starting Document Upload & Agent API Server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
