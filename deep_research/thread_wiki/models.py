"""Data models for thread-level LLM Wiki integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class IngestPhase(str, Enum):
    """Phases of the wiki ingest lifecycle."""

    IDLE = "idle"
    INITIALIZING = "initializing"
    STAGING_SOURCES = "staging_sources"
    ANALYZING = "analyzing"
    APPLYING = "applying"
    REFRESHING_INDEX = "refreshing_index"
    MERGING = "merging"
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
class SourceCitation:
    """A single source reference parsed from an answer.

    Citation kinds:
    - ``raw``: an uploaded document raw path, e.g. ``/raw/report.pdf.md``.
      ``page`` carries the PDF page number when derivable.
    - ``web``: a web URL, with ``url`` set and ``locator`` holding the title.
    - ``section``: a ``file#Heading`` reference, with ``locator`` holding the
      heading text.
    """

    kind: str = "raw"
    raw_path: str | None = None
    page: int | None = None
    locator: str | None = None
    url: str | None = None


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


# ── Wiki Page Metadata (YAML frontmatter) ──────────────────────────────────────

# Valid page categories matching the structured subdirectory layout.
WIKI_PAGE_CATEGORIES = frozenset({
    "entity", "concept", "source", "comparison", "synthesis", "query", "uncategorized",
})

# Directory name → category mapping.
CATEGORY_DIRECTORIES: dict[str, str] = {
    "entities": "entity",
    "concepts": "concept",
    "sources": "source",
    "comparisons": "comparison",
    "synthesis": "synthesis",
    "query": "query",
}


@dataclass
class WikiPageMetadata:
    """YAML frontmatter fields for a wiki page."""

    title: str
    category: str = "uncategorized"
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    updated: str = ""  # ISO-8601 date string

    def to_frontmatter(self) -> str:
        """Serialize metadata as a YAML frontmatter block."""
        import yaml

        data: dict[str, object] = {
            "title": self.title,
            "category": self.category,
        }
        if self.summary:
            data["summary"] = self.summary
        if self.tags:
            data["tags"] = self.tags
        if self.sources:
            data["sources"] = self.sources
        if self.updated:
            data["updated"] = self.updated
        else:
            data["updated"] = datetime.now(UTC).strftime("%Y-%m-%d")

        yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False).strip()
        return f"---\n{yaml_str}\n---\n"


def parse_frontmatter(content: str) -> tuple[WikiPageMetadata, str]:
    """Parse YAML frontmatter from markdown content.

    Returns a ``(metadata, body)`` tuple.  If no valid frontmatter is found,
    metadata fields are populated with sensible defaults (title from first
    heading, category ``"uncategorized"``).
    """
    import yaml

    metadata = WikiPageMetadata(title="", category="uncategorized")
    body = content

    if not content.startswith("---"):
        # No frontmatter — derive title from first heading.
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                metadata.title = stripped.lstrip("# ").strip()
                break
        return metadata, body

    # Find closing `---`.
    end_idx = content.find("\n---", 3)
    if end_idx == -1:
        return metadata, body

    yaml_str = content[3:end_idx].strip()
    body = content[end_idx + 4:].lstrip("\n")

    try:
        frontmatter = yaml.safe_load(yaml_str)
    except yaml.YAMLError:
        logger.debug("Failed to parse YAML frontmatter; falling back to defaults.")
        return metadata, body

    if not isinstance(frontmatter, dict):
        return metadata, body

    metadata.title = str(frontmatter.get("title", metadata.title))
    category = str(frontmatter.get("category", "uncategorized")).lower()
    metadata.category = category if category in WIKI_PAGE_CATEGORIES else "uncategorized"
    metadata.summary = str(frontmatter.get("summary", ""))
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        metadata.tags = [str(t) for t in tags]
    sources = frontmatter.get("sources", [])
    if isinstance(sources, list):
        metadata.sources = [str(s) for s in sources]
    metadata.updated = str(frontmatter.get("updated", ""))

    return metadata, body


# ── Contradiction Tracking ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Contradiction:
    """A tracked contradiction between two or more source claims."""

    wiki_page: str  # Relative path of the page documenting the contradiction
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    resolved: bool = False
    resolution_note: str = ""


@dataclass(frozen=True)
class WikiQueryResult:
    """Result from a wiki query operation."""

    answer: str
    filed_path: str | None = None
    sources_cited: list[SourceCitation] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
