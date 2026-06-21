"""Data models for thread-level LLM Wiki integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path


class IngestPhase(str, Enum):
    """Phases of the wiki ingest lifecycle."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    STAGING_SOURCES = "staging_sources"
    ANALYZING = "analyzing"
    APPLYING = "applying"
    REFRESHING_INDEX = "refreshing_index"
    READY = "ready"
    ERROR = "error"
    CANCELLED = "cancelled"


# Phases considered "in progress" (not terminal).
ACTIVE_PHASES = frozenset({
    IngestPhase.INITIALIZING,
    IngestPhase.STAGING_SOURCES,
    IngestPhase.ANALYZING,
    IngestPhase.APPLYING,
    IngestPhase.REFRESHING_INDEX,
})

# Terminal phases indicating the ingest is no longer running.
TERMINAL_PHASES = frozenset({
    IngestPhase.READY,
    IngestPhase.ERROR,
    IngestPhase.CANCELLED,
    IngestPhase.IDLE,
})

# Phase → approximate progress percentage mapping.
PHASE_PROGRESS = {
    IngestPhase.IDLE: 0,
    IngestPhase.INITIALIZING: 5,
    IngestPhase.STAGING_SOURCES: 15,
    IngestPhase.ANALYZING: 40,
    IngestPhase.APPLYING: 70,
    IngestPhase.REFRESHING_INDEX: 90,
    IngestPhase.READY: 100,
    IngestPhase.ERROR: -1,
    IngestPhase.CANCELLED: -1,
}


@dataclass
class IngestProgress:
    """Thread-safe progress tracker for a single wiki ingest operation."""

    thread_id: str
    phase: IngestPhase = IngestPhase.IDLE
    progress: int = 0
    detail: str = ""
    source_count: int = 0
    sources_processed: int = 0
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None

    def advance(self, phase: IngestPhase, detail: str = "", *, extra_progress: int = 0) -> None:
        """Advance to a new phase, updating progress percentage."""
        self.phase = phase
        self.detail = detail
        base = PHASE_PROGRESS.get(phase, 0)
        self.progress = max(0, min(100, base + extra_progress))

    def mark_complete(self, detail: str = "Ingest completed successfully.") -> None:
        """Mark the ingest as successfully finished."""
        self.phase = IngestPhase.READY
        self.progress = 100
        self.detail = detail
        self.completed_at = datetime.now(UTC).isoformat()

    def mark_error(self, error: str) -> None:
        """Mark the ingest as failed."""
        self.phase = IngestPhase.ERROR
        self.progress = -1
        self.detail = ""
        self.error = error
        self.completed_at = datetime.now(UTC).isoformat()

    def mark_cancelled(self, reason: str = "Cancelled by client.") -> None:
        """Mark the ingest as cancelled."""
        self.phase = IngestPhase.CANCELLED
        self.progress = -1
        self.detail = reason
        self.completed_at = datetime.now(UTC).isoformat()

    def is_active(self) -> bool:
        """Return True if the ingest is still running."""
        return self.phase in ACTIVE_PHASES

    def is_terminal(self) -> bool:
        """Return True if the ingest has reached a terminal state."""
        return self.phase in TERMINAL_PHASES

    def to_dict(self) -> dict:
        """Serialize progress state for API responses."""
        return {
            "thread_id": self.thread_id,
            "phase": self.phase.value,
            "progress": self.progress,
            "detail": self.detail,
            "source_count": self.source_count,
            "sources_processed": self.sources_processed,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "is_active": self.is_active(),
        }


@dataclass(frozen=True)
class WikiQueryRequest:
    """Request payload for a wiki query operation."""

    question: str
    thread_id: str
    file_results: bool = True


@dataclass(frozen=True)
class WikiQueryResult:
    """Result from a wiki query operation."""

    answer: str
    filed_path: str | None = None
    sources_cited: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ThreadWikiPaths:
    """Resolved filesystem paths for a thread's wiki workspace."""

    thread_id: str
    docs_dir: Path  # ./docs/threads/<thread-id>/
    wiki_dir: Path  # ./docs/threads-wiki/<thread-id>/
    raw_dir: Path  # ./docs/threads-wiki/<thread-id>/raw/
    wiki_content: Path  # ./docs/threads-wiki/<thread-id>/wiki/

    @classmethod
    def resolve(cls, thread_id: str, base_dir: Path) -> ThreadWikiPaths:
        """Resolve paths for a given thread ID relative to a base directory."""
        docs_dir = base_dir / "docs" / "threads" / thread_id
        wiki_dir = base_dir / "docs" / "threads-wiki" / thread_id
        return cls(
            thread_id=thread_id,
            docs_dir=docs_dir,
            wiki_dir=wiki_dir,
            raw_dir=wiki_dir / "raw",
            wiki_content=wiki_dir / "wiki",
        )
