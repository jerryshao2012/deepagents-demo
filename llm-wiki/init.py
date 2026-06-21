"""Init-specific workflow for the LLM wiki."""

from __future__ import annotations

import helpers
from models import CliDeps, RunResult, RunnerConfig


def run_init(config: RunnerConfig, deps: CliDeps) -> RunResult:
    """Initialize a local topic repo directory layout."""
    config.wiki_dir.mkdir(parents=True, exist_ok=True)
    helpers._ensure_no_symlinks(config.wiki_dir)
    helpers._ensure_scaffold(config.wiki_dir, config.topic)
    return RunResult(answer=f"Initialized local wiki repository at {config.wiki_dir}")
