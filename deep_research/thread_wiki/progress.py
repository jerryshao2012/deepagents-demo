"""Async progress tracking and cancellation for thread wiki ingest operations.

Maintains a global registry of active ingest tasks keyed by thread_id.
Supports:
- Real-time progress updates (polled or SSE-streamed).
- Cancellation: calling ``cancel_ingest(thread_id)`` sets a cancellation flag
  and cancels the underlying asyncio.Task. The ingest coroutine checks the flag
  between phases and raises ``asyncio.CancelledError`` promptly.
"""

from __future__ import annotations

import asyncio
from typing import NamedTuple

from .models import IngestProgress


class _IngestEntry(NamedTuple):
    """Internal bookkeeping for one active ingest."""
    progress: IngestProgress
    task: asyncio.Task
    cancel_event: asyncio.Event


# Global registry: thread_id → active ingest entry.
_active_ingests: dict[str, _IngestEntry] = {}
_registry_lock = asyncio.Lock()


async def register_ingest(
        thread_id: str,
        task: asyncio.Task,
) -> IngestProgress:
    """Register a new ingest task for a thread, replacing any stale entry."""
    async with _registry_lock:
        existing = _active_ingests.pop(thread_id, None)
        if existing and not existing.task.done():
            # Cancel the previous ingest before starting a new one.
            existing.cancel_event.set()
            existing.task.cancel()

        progress = IngestProgress(thread_id=thread_id)
        cancel_event = asyncio.Event()
        _active_ingests[thread_id] = _IngestEntry(
            progress=progress,
            task=task,
            cancel_event=cancel_event,
        )
        return progress


async def get_progress(thread_id: str) -> IngestProgress | None:
    """Return the current progress tracker for a thread, or None."""
    async with _registry_lock:
        entry = _active_ingests.get(thread_id)
        if entry is not None:
            return entry.progress
    return None


async def cancel_ingest(thread_id: str, *, reason: str = "Cancelled by client.") -> bool:
    """Cancel an active ingest for the given thread.

    Returns True if a running ingest was found and cancelled, False otherwise.
    """
    async with _registry_lock:
        entry = _active_ingests.get(thread_id)
        if entry is None:
            return False
        if entry.task.done():
            # Already finished; clean up stale entry.
            _active_ingests.pop(thread_id, None)
            return False

        # Signal the coroutine to stop at the next checkpoint.
        entry.cancel_event.set()
        entry.progress.mark_cancelled(reason)
        entry.task.cancel()
        return True


async def cleanup_terminal(thread_id: str) -> None:
    """Remove a terminal ingest entry from the registry."""
    async with _registry_lock:
        entry = _active_ingests.get(thread_id)
        if entry is not None and (entry.task.done() or entry.progress.is_terminal()):
            _active_ingests.pop(thread_id, None)


def is_cancelled_sync(cancel_event: asyncio.Event) -> bool:
    """Check cancellation flag without awaiting (for use inside sync callbacks)."""
    return cancel_event.is_set()


async def check_cancellation(cancel_event: asyncio.Event, *, phase_name: str = "") -> None:
    """Raise ``asyncio.CancelledError`` if cancellation has been requested.

    Call this between ingest phases so the coroutine exits promptly.
    """
    if cancel_event.is_set():
        raise asyncio.CancelledError(
            f"Ingest cancelled{' during ' + phase_name if phase_name else ''}."
        )
