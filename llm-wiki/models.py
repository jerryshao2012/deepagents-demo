"""Shared data models for LLM wiki workflows."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Mode = Literal["init", "ingest", "query", "lint"]


@dataclass(frozen=True)
class RunnerConfig:
    """Parsed runner configuration."""

    mode: Mode
    topic: str
    wiki_dir: Path
    sources: tuple[Path, ...]
    note: str | None
    question: str | None
    model: str | None
    review: bool


@dataclass(frozen=True)
class CliDeps:
    """Injectable dependencies for tests."""

    run_agent_mode: Callable[[Path, str, str, str | None], str]
    run_agent_review_mode: Callable[[Path, str, str, str | None], str]
    ask_user: Callable[[str], str]
    tempdir_factory: Callable[[], tempfile.TemporaryDirectory[str]]


@dataclass(frozen=True)
class RunResult:
    """Output from a runner invocation."""

    answer: str | None
