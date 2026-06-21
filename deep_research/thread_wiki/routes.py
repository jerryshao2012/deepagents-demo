"""FastAPI routes for thread-level wiki management.

Provides endpoints for:
- Triggering wiki ingest (background with progress tracking)
- Querying ingest progress (polling + SSE streaming)
- Cancelling an in-progress ingest
- Querying the wiki knowledge base
- Running lint reconciliation after document deletions
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import progress as progress_tracker
from .models import ThreadWikiPaths
from .service import run_ingest, run_lint, run_query

# ── Router setup ──────────────────────────────────────────────────────────────

router = APIRouter(tags=["Wiki"])

# Base directory for resolving thread paths.
# This is set once at import time relative to this file's parent (deep_research/).
_BASE_DIR = Path(__file__).resolve().parent.parent


def _sse_frame(event: str, data: Any, event_id: int | None = None) -> str:
    """Build one SSE frame."""
    payload = json.dumps(data, default=str)
    id_part = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_part}event: {event}\ndata: {payload}\n\n"


# ── Pydantic models ───────────────────────────────────────────────────────────

class WikiIngestRequest(BaseModel):
    """Request body for triggering wiki ingest."""
    note: str | None = None
    topic: str | None = None


class WikiQueryRequestModel(BaseModel):
    """Request body for querying the wiki."""
    question: str
    file_results: bool = True


class WikiLintRequest(BaseModel):
    """Request body for running wiki lint."""
    note: str | None = None
    topic: str | None = None


class WikiIngestResponse(BaseModel):
    """Response from triggering wiki ingest."""
    thread_id: str
    status: str
    message: str


class WikiStatusResponse(BaseModel):
    """Response for wiki ingest status."""
    thread_id: str
    phase: str
    progress: int
    detail: str
    source_count: int
    sources_processed: int
    error: str | None
    started_at: str | None
    completed_at: str | None
    is_active: bool
    wiki_ready: bool


class WikiQueryResponse(BaseModel):
    """Response from a wiki query."""
    answer: str
    filed_path: str | None = None
    sources_cited: list[str] = Field(default_factory=list)


class WikiLintResponse(BaseModel):
    """Response from a wiki lint operation."""
    result: str
    topic: str


# ── Auth dependency (self-contained to avoid circular import with server.py) ──

async def _wiki_get_current_user(request: Request) -> dict:
    """Authenticate wiki routes using the same auth pattern as server.py.

    Delegates to server.get_current_user at request time (not import time)
    to avoid circular imports.
    """
    import server as _server
    return await _server.get_current_user(request)


# ── Helper ────────────────────────────────────────────────────────────────────

def _resolve_paths(thread_id: str) -> ThreadWikiPaths:
    """Resolve wiki paths for a thread, validating the docs directory exists."""
    paths = ThreadWikiPaths.resolve(thread_id, _BASE_DIR)
    if not paths.docs_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No documents found for thread '{thread_id}'. Upload documents first.",
        )
    return paths


def _topic_from_thread(thread_id: str, override: str | None = None) -> str:
    """Derive a topic label from the thread ID or use the override."""
    if override:
        return override
    # Use a short form of the thread_id as the topic label.
    short = thread_id[:8]
    return f"Thread {short}"


def _wiki_is_ready(paths: ThreadWikiPaths) -> bool:
    """Check if the wiki has been initialized and has content."""
    index_path = paths.wiki_content / "index.md"
    if not index_path.exists():
        return False
    content = index_path.read_text(encoding="utf-8")
    return "_No pages yet._" not in content


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post(
    "/threads/{thread_id}/wiki/ingest",
    response_model=WikiIngestResponse,
)
async def trigger_wiki_ingest(
        thread_id: str,
        body: WikiIngestRequest = WikiIngestRequest(),
        current_user=Depends(_wiki_get_current_user),
) -> WikiIngestResponse:
    """Trigger wiki ingest for a thread's uploaded documents.

    If an ingest is already running, it will be cancelled and replaced.
    The ingest runs as a background task; poll `/wiki/status` or stream
    `/wiki/progress` for real-time updates.
    """
    paths = _resolve_paths(thread_id)
    topic = _topic_from_thread(thread_id, body.topic)

    # Cancel any existing ingest for this thread.
    await progress_tracker.cancel_ingest(thread_id, reason="Replaced by new ingest request.")

    # Pre-create a placeholder task to register progress first, then replace
    # it with the real task. This avoids a race where the background function
    # looks up the registry before registration completes.
    placeholder_task: asyncio.Task = asyncio.create_task(asyncio.sleep(0))
    prog = await progress_tracker.register_ingest(thread_id, placeholder_task)

    # Now create the real background task with the registered progress/cancel.
    cancel_event = progress_tracker._active_ingests[thread_id].cancel_event
    task = asyncio.create_task(
        _run_ingest_background(paths, topic, body.note, prog, cancel_event),
        name=f"wiki-ingest-{thread_id}",
    )

    # Update the registry entry with the real task.
    progress_tracker._active_ingests[thread_id] = progress_tracker._IngestEntry(
        progress=prog, task=task, cancel_event=cancel_event,
    )
    prog.advance(prog.phase, "Ingest queued.")

    return WikiIngestResponse(
        thread_id=thread_id,
        status="started",
        message="Wiki ingest started. Poll /wiki/status or stream /wiki/progress for updates.",
    )


async def _run_ingest_background(
        paths: ThreadWikiPaths,
        topic: str,
        note: str | None,
        progress_obj,
        cancel_event: asyncio.Event,
) -> None:
    """Background ingest worker with directly injected progress and cancel objects."""
    try:
        await run_ingest(paths, topic, progress_obj, cancel_event, note=note)
    except asyncio.CancelledError:
        logger.info("Ingest cancelled for thread %s", paths.thread_id)
    except Exception:
        logger.exception("Ingest failed for thread %s", paths.thread_id)
    finally:
        await progress_tracker.cleanup_terminal(paths.thread_id)


@router.get(
    "/threads/{thread_id}/wiki/status",
    response_model=WikiStatusResponse,
)
async def get_wiki_status(
        thread_id: str,
        current_user=Depends(_wiki_get_current_user),
) -> WikiStatusResponse:
    """Get current wiki ingest status and progress for a thread."""
    paths = ThreadWikiPaths.resolve(thread_id, _BASE_DIR)
    prog = await progress_tracker.get_progress(thread_id)

    if prog is None:
        # No active ingest — check if wiki is already built.
        ready = _wiki_is_ready(paths)
        return WikiStatusResponse(
            thread_id=thread_id,
            phase="ready" if ready else "idle",
            progress=100 if ready else 0,
            detail="Wiki is ready." if ready else "No ingest has been run yet.",
            source_count=0,
            sources_processed=0,
            error=None,
            started_at=None,
            completed_at=None,
            is_active=False,
            wiki_ready=ready,
        )

    return WikiStatusResponse(
        thread_id=thread_id,
        phase=prog.phase.value,
        progress=prog.progress,
        detail=prog.detail,
        source_count=prog.source_count,
        sources_processed=prog.sources_processed,
        error=prog.error,
        started_at=prog.started_at,
        completed_at=prog.completed_at,
        is_active=prog.is_active(),
        wiki_ready=_wiki_is_ready(paths),
    )


@router.get("/threads/{thread_id}/wiki/progress")
async def stream_wiki_progress(
        thread_id: str,
        current_user=Depends(_wiki_get_current_user),
):
    """SSE stream for real-time ingest progress updates.

    The frontend can connect to this endpoint and receive progress events
    as the ingest proceeds. The stream ends when the ingest reaches a
    terminal state (ready, error, or cancelled).
    """
    from fastapi.responses import StreamingResponse

    async def event_stream():
        seq = 0
        last_phase = None
        last_progress = None

        while True:
            prog = await progress_tracker.get_progress(thread_id)

            if prog is None:
                # No active ingest.
                paths = ThreadWikiPaths.resolve(thread_id, _BASE_DIR)
                ready = _wiki_is_ready(paths)
                yield _sse_frame("end", {
                    "thread_id": thread_id,
                    "phase": "ready" if ready else "idle",
                    "progress": 100 if ready else 0,
                    "wiki_ready": ready,
                }, event_id=seq)
                return

            # Emit on phase change.
            if prog.phase != last_phase:
                yield _sse_frame("progress", prog.to_dict(), event_id=seq)
                seq += 1
                last_phase = prog.phase

            # Emit on progress percentage change.
            if prog.progress != last_progress:
                yield _sse_frame("progress", prog.to_dict(), event_id=seq)
                seq += 1
                last_progress = prog.progress

            # Terminal state → emit end and close stream.
            if prog.is_terminal():
                paths = ThreadWikiPaths.resolve(thread_id, _BASE_DIR)
                yield _sse_frame("end", {
                    **prog.to_dict(),
                    "wiki_ready": _wiki_is_ready(paths),
                }, event_id=seq)
                return

            await asyncio.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/threads/{thread_id}/wiki/ingest/cancel",
)
async def cancel_wiki_ingest(
        thread_id: str,
        current_user=Depends(_wiki_get_current_user),
) -> dict[str, Any]:
    """Cancel an in-progress wiki ingest for a thread.

    Returns immediately. The background task will stop at the next
    phase checkpoint.
    """
    cancelled = await progress_tracker.cancel_ingest(
        thread_id, reason="Cancelled by client request."
    )
    return {
        "thread_id": thread_id,
        "cancelled": cancelled,
        "message": "Ingest cancelled." if cancelled else "No active ingest to cancel.",
    }


@router.post(
    "/threads/{thread_id}/wiki/query",
    response_model=WikiQueryResponse,
)
async def query_wiki(
        thread_id: str,
        body: WikiQueryRequestModel,
        current_user=Depends(_wiki_get_current_user),
) -> WikiQueryResponse:
    """Query the thread's wiki knowledge base.

    Returns a grounded answer with citations from the ingested documents.
    If the answer has durable value, it will be filed into the wiki for
    future reference.
    """
    paths = _resolve_paths(thread_id)

    # Check that wiki is ready before allowing queries.
    if not _wiki_is_ready(paths):
        raise HTTPException(
            status_code=409,
            detail=(
                "Wiki is not ready yet. Run ingest first or wait for the "
                "current ingest to complete."
            ),
        )

    topic = _topic_from_thread(thread_id)
    result: WikiQueryResult = await run_query(
        paths, topic, body.question, file_results=body.file_results
    )

    return WikiQueryResponse(
        answer=result.answer,
        filed_path=result.filed_path,
        sources_cited=result.sources_cited,
    )


@router.post(
    "/threads/{thread_id}/wiki/lint",
    response_model=WikiLintResponse,
)
async def lint_wiki(
        thread_id: str,
        body: WikiLintRequest = WikiLintRequest(),
        current_user=Depends(_wiki_get_current_user),
) -> WikiLintResponse:
    """Run lint reconciliation on the thread's wiki.

    Use this after document deletions to reconcile stale references,
    remove orphan pages, and refresh cross-links.
    """
    paths = _resolve_paths(thread_id)

    if not paths.wiki_dir.exists():
        raise HTTPException(
            status_code=409,
            detail="Wiki has not been initialized. Run ingest first.",
        )

    topic = _topic_from_thread(thread_id, body.topic)
    result = await run_lint(paths, topic, note=body.note)

    return WikiLintResponse(result=result, topic=topic)


import logging

logger = logging.getLogger(__name__)
