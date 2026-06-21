"""Unit tests for LLM wiki local setup and ingest helpers."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
# Add sibling deepagents repo path to sys.path to bypass editable install issues
deepagents_path = Path(__file__).resolve().parents[4] / "deepagents" / "libs" / "deepagents"
sys.path.insert(0, str(deepagents_path))

import helpers

import lint as lint_helpers
import query as query_helpers


def _make_deps(
        run_agent_mode: Callable[..., str] | None = None,
        run_agent_review_mode: Callable[..., str] | None = None,
        ask_user: Callable[[str], str] | None = None,
) -> helpers.CliDeps:
    """Build injectable dependencies for helper tests."""
    return helpers.CliDeps(
        run_agent_mode=run_agent_mode or (lambda *_args: "apply"),
        run_agent_review_mode=run_agent_review_mode or (lambda *_args: "review"),
        ask_user=ask_user or (lambda _prompt: "y"),
        tempdir_factory=lambda: tempfile.TemporaryDirectory(),
    )


def _log_headings(log_text: str) -> list[str]:
    """Return parseable timeline heading lines from log markdown."""
    return [line for line in log_text.splitlines() if line.startswith("## [")]


def test_parse_config_accepts_wiki_dir(tmp_path: Path) -> None:
    """Parse direct wiki_dir input into configuration."""
    config = helpers.parse_config(
        [
            "--mode",
            "init",
            "--wiki-dir",
            str(tmp_path / "wiki"),
        ]
    )

    assert config.wiki_dir == (tmp_path / "wiki").resolve()
    assert config.topic == "Wiki"
    assert config.review is False


def test_parse_config_defaults_topic_from_wiki_dir(tmp_path: Path) -> None:
    """Default topic name from wiki-dir path name."""
    config = helpers.parse_config(
        [
            "--mode",
            "init",
            "--wiki-dir",
            str(tmp_path / "ada-lovelace-wiki"),
        ]
    )

    assert config.topic == "Ada Lovelace Wiki"
    assert config.review is False


def test_parse_config_sets_review_when_requested(tmp_path: Path) -> None:
    """Enable review mode when --review is passed."""
    source = tmp_path / "source.md"
    source.write_text("content", encoding="utf-8")
    config = helpers.parse_config(
        [
            "--mode",
            "ingest",
            "--wiki-dir",
            str(tmp_path / "wiki"),
            "--source",
            str(source),
            "--review",
        ]
    )

    assert config.review is True


def test_parse_config_requires_source_for_ingest(tmp_path: Path) -> None:
    """Require at least one source path in ingest mode."""
    with pytest.raises(SystemExit):
        helpers.parse_config(
            [
                "--mode",
                "ingest",
                "--wiki-dir",
                str(tmp_path / "wiki"),
            ]
        )


def test_parse_config_requires_question_for_query(tmp_path: Path) -> None:
    """Require a question in query mode."""
    with pytest.raises(SystemExit):
        helpers.parse_config(
            [
                "--mode",
                "query",
                "--wiki-dir",
                str(tmp_path / "wiki"),
            ]
        )


def test_run_init_creates_agents_md_when_missing(tmp_path: Path) -> None:
    """Initialize folders and write guidance rules in init mode."""
    wiki_dir = tmp_path / "my-topic-wiki"
    config = helpers.RunnerConfig(
        mode="init",
        topic="My Topic",
        wiki_dir=wiki_dir,
        sources=(),
        note=None,
        question=None,
        model=None,
        review=False,
    )
    deps = _make_deps()

    helpers.run(config, deps)

    assert (wiki_dir / "raw").is_dir()
    assert (wiki_dir / "wiki").is_dir()
    assert (wiki_dir / "wiki" / "index.md").is_file()
    assert (wiki_dir / "log.md").is_file()

    agents_text = (wiki_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert "# My Topic Wiki" in agents_text
    assert "Rule" in agents_text


def test_run_init_preserves_existing_agents_md(tmp_path: Path) -> None:
    """Keep custom edits in AGENTS.md on initialization."""
    wiki_dir = tmp_path / "custom-wiki"
    wiki_dir.mkdir(parents=True)
    agents_path = wiki_dir / "AGENTS.md"
    agents_path.write_text("custom user configuration", encoding="utf-8")

    config = helpers.RunnerConfig(
        mode="init",
        topic="Custom",
        wiki_dir=wiki_dir,
        sources=(),
        note=None,
        question=None,
        model=None,
        review=False,
    )
    deps = _make_deps()

    helpers.run(config, deps)

    assert agents_path.read_text(encoding="utf-8") == "custom user configuration"


def test_run_ingest_workspace_runs_review_then_apply(tmp_path: Path) -> None:
    """Execute review and apply phases when confirming the takeaways."""
    source = tmp_path / "source.md"
    source.write_text("hello\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "raw").mkdir(parents=True)
    (workspace_dir / "wiki").mkdir(parents=True)
    (workspace_dir / "wiki" / "index.md").write_text("# Ada Wiki\n", encoding="utf-8")
    (workspace_dir / "log.md").write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_review(*_args: object) -> str:
        calls.append("review")
        return "review summary"

    def fake_apply(*_args: object) -> str:
        calls.append("apply")
        return "apply summary"

    deps = _make_deps(
        run_agent_mode=fake_apply,
        run_agent_review_mode=fake_review,
        ask_user=lambda _prompt: "y",
    )

    config = helpers.RunnerConfig(
        mode="ingest",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(source,),
        note=None,
        question=None,
        model=None,
        review=True,
    )

    result = helpers.run(config, deps)

    assert result.answer == "apply summary"
    assert calls == ["review", "apply"]
    log_text = (workspace_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest.review | outcome=completed" in log_text
    assert "ingest.apply | outcome=applied" in log_text


def test_run_ingest_workspace_cancelled_skips_apply(tmp_path: Path) -> None:
    """Abort the update phase if the user declines confirmation."""
    source = tmp_path / "source.md"
    source.write_text("hello\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "raw").mkdir(parents=True)
    (workspace_dir / "wiki").mkdir(parents=True)
    (workspace_dir / "wiki" / "index.md").write_text("# Ada Wiki\n", encoding="utf-8")
    (workspace_dir / "log.md").write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_review(*_args: object) -> str:
        calls.append("review")
        return "review summary"

    def fake_apply(*_args: object) -> str:
        calls.append("apply")
        return "should not run"

    deps = _make_deps(
        run_agent_mode=fake_apply,
        run_agent_review_mode=fake_review,
        ask_user=lambda _prompt: "n",
    )

    config = helpers.RunnerConfig(
        mode="ingest",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(source,),
        note=None,
        question=None,
        model=None,
        review=True,
    )

    result = helpers.run(config, deps)

    assert result.answer and "canceled" in result.answer.lower()
    assert calls == ["review"]
    log_text = (workspace_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest.review | outcome=completed" in log_text
    assert "ingest.apply | outcome=canceled" in log_text


def test_run_ingest_workspace_default_skips_review(tmp_path: Path) -> None:
    """Apply ingest directly when review mode is not enabled."""
    source = tmp_path / "source.md"
    source.write_text("hello\n", encoding="utf-8")

    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "raw").mkdir(parents=True)
    (workspace_dir / "wiki").mkdir(parents=True)
    (workspace_dir / "wiki" / "index.md").write_text("# Ada Wiki\n", encoding="utf-8")
    (workspace_dir / "log.md").write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_review(*_args: object) -> str:
        calls.append("review")
        return "review summary"

    def fake_apply(*_args: object) -> str:
        calls.append("apply")
        return "apply summary"

    deps = _make_deps(
        run_agent_mode=fake_apply,
        run_agent_review_mode=fake_review,
        ask_user=lambda _prompt: "n",
    )

    config = helpers.RunnerConfig(
        mode="ingest",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(source,),
        note=None,
        question=None,
        model=None,
        review=False,
    )

    result = helpers.run(config, deps)

    assert result.answer == "apply summary"
    assert calls == ["apply"]
    log_text = (workspace_dir / "log.md").read_text(encoding="utf-8")
    assert "ingest.apply | outcome=applied" in log_text
    assert "ingest.review |" not in log_text


def test_run_lint_workspace_returns_summary_and_updates_index_log(tmp_path: Path) -> None:
    """Lint should run as apply-only, refresh index, and append log entry."""
    workspace_dir = tmp_path / "workspace"
    wiki_dir = workspace_dir / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "index.md").write_text("# Ada Wiki\n\n## Pages\n", encoding="utf-8")
    (wiki_dir / "history.md").write_text("# History\n", encoding="utf-8")
    (workspace_dir / "log.md").write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_apply(*_args: object) -> str:
        calls.append("apply")
        return (
            "## Reconciled Changes\n- Fixed contradiction.\n\n"
            "## Remaining Gaps\n- Gaps.\n\n"
            "## Suggested Next Questions and Sources\n- Questions."
        )

    deps = _make_deps(
        run_agent_mode=fake_apply,
    )

    config = helpers.RunnerConfig(
        mode="lint",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(),
        note="Focus on contradictions.",
        question=None,
        model=None,
        review=False,
    )

    summary = lint_helpers.run_lint_workspace(config, workspace_dir, deps)

    assert calls == ["apply"]
    assert "## Reconciled Changes" in summary
    index_text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "(history.md)" in index_text

    log_text = (workspace_dir / "log.md").read_text(encoding="utf-8")
    assert "lint.apply | outcome=applied" in log_text
    assert "Fixed contradiction." in log_text


def test_run_query_workspace_skip_keeps_query_read_only(tmp_path: Path) -> None:
    """Skip filing writes no query files but logs the interaction."""
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "wiki").mkdir(parents=True)
    (workspace_dir / "wiki" / "index.md").write_text("# Ada Wiki\n", encoding="utf-8")
    log_path = workspace_dir / "log.md"
    log_path.write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_review(*_args: object) -> str:
        calls.append("review")
        return (
            "ANSWER:\nThis answer is ad-hoc.\n\n"
            "FILING_DECISION: skip\n"
            "FILING_REASON: low reuse"
        )

    def fake_apply(*_args: object) -> str:
        calls.append("apply")
        return "should not run"

    deps = _make_deps(
        run_agent_mode=fake_apply,
        run_agent_review_mode=fake_review,
    )

    config = helpers.RunnerConfig(
        mode="query",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(),
        note=None,
        question="What changed?",
        model=None,
        review=False,
    )

    result = query_helpers.run_query_workspace(config, workspace_dir, deps)

    assert result.should_push is True
    assert result.filed_path is None
    assert "ad-hoc" in result.answer
    assert calls == ["review"]
    log_text = log_path.read_text(encoding="utf-8")
    assert "query.review | outcome=skip" in log_text
    assert "query.apply |" not in log_text


def test_run_query_workspace_files_durable_answer(tmp_path: Path) -> None:
    """File durable query answers into wiki/query/<slug>.md and log the run."""
    workspace_dir = tmp_path / "workspace"
    (workspace_dir / "wiki").mkdir(parents=True)
    (workspace_dir / "wiki" / "index.md").write_text("# Ada Wiki\n", encoding="utf-8")
    (workspace_dir / "log.md").write_text("# Change Log\n", encoding="utf-8")

    calls: list[str] = []

    def fake_review(*_args: object) -> str:
        calls.append("review")
        return (
            "ANSWER:\nAda introduced analytical patterns.\n\n"
            "FILING_DECISION: file\n"
            "FILING_REASON: reusable synthesis"
        )

    def fake_apply(
            workspace_dir_arg: Path, _topic: str, prompt: str, _model: str | None
    ) -> str:
        calls.append("apply")
        target = workspace_dir_arg / "wiki" / "query" / "what-did-ada-do.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# What Did Ada Do\n\n## Answer\n\nDurable synthesis.\n",
            encoding="utf-8",
        )
        return "filed"

    deps = _make_deps(
        run_agent_mode=fake_apply,
        run_agent_review_mode=fake_review,
    )

    config = helpers.RunnerConfig(
        mode="query",
        topic="Ada",
        wiki_dir=workspace_dir,
        sources=(),
        note=None,
        question="What did Ada do?",
        model=None,
        review=False,
    )

    result = query_helpers.run_query_workspace(config, workspace_dir, deps)

    assert result.should_push is True
    assert result.filed_path == "/wiki/query/what-did-ada-do.md"
    assert "analytical patterns" in result.answer
    assert calls == ["review", "apply"]

    index_text = (workspace_dir / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "(query/what-did-ada-do.md)" in index_text

    log_text = (workspace_dir / "log.md").read_text(encoding="utf-8")
    assert "query.review | outcome=file" in log_text
    assert "query.apply | outcome=filed" in log_text


def test_stage_sources_with_pdf(tmp_path: Path) -> None:
    """Stage a PDF file and verify it is converted to a text markdown file in raw."""
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    workspace_dir = tmp_path / "workspace"
    staged = helpers._stage_sources([pdf_path], workspace_dir)
    assert len(staged) == 1
    staged_file = staged[0]
    assert staged_file.name == "test.pdf.md"
    assert staged_file.exists()
    # The file should be a valid text file containing either empty/extracted content
    content = staged_file.read_text(encoding="utf-8")
    assert isinstance(content, str)
