"""Helper utilities for the LLM wiki example."""

from __future__ import annotations

import argparse
import errno
import os
import tempfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
from deepagents.middleware.filesystem import FilesystemPermission

import index as index_helpers
import log as log_helpers
from models import CliDeps, RunResult, RunnerConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from deepagents.backends.protocol import SandboxBackendProtocol
    from ingest import IngestResult


def _resolve_model():
    """Return a LangChain chat model from the environment via model_factory."""
    from model_factory import get_configured_model

    return get_configured_model()


_ALLOWED_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
_ALLOWED_SOURCE_SUFFIXES = _ALLOWED_TEXT_SUFFIXES | {".pdf"}

_BASE_SYSTEM_PROMPT = """You are an expert research synthesizer building a long-lived topic knowledge base.

Mission:
- Build an accurate, high-signal, source-grounded topic corpus in `/wiki/`.
- Treat `/raw/` as immutable evidence inputs.
- Convert raw notes into canonical, reusable understanding.

Reasoning style:
- Read primary source material before writing.
- Distinguish facts from inferences.
- Prefer compression-by-structure over compression-by-omission.
- Keep uncertainty explicit.
- Resolve contradictions when possible; otherwise record both claims and state what is unresolved.

Writing and organization rules:
- Maintain canonical pages per concept/entity/theme rather than many overlapping fragments.
- Keep pages scannable with clear headings.
- Include concise "What changed" summaries in your responses for runner-managed logging.
- Keep `/wiki/index.md` authoritative for navigation.
- Use recent `/log.md` entries as operational recency context before major synthesis.

Evidence rules:
- Every non-trivial claim should be traceable to the ingested source set.
- Avoid introducing unsupported external facts.
- If evidence is weak or missing, say so directly.

Filesystem policy:
- Never write to `/raw/`.
- Never edit `/log.md`; the runner maintains append-only interaction entries.
- Write only under `/wiki/`.
"""


class WikiError(RuntimeError):
    """Raised when the LLM wiki cannot complete a requested operation."""


def _slugify_topic(topic: str) -> str:
    """Convert a topic label into a stable slug."""
    slug_chars: list[str] = []
    last_dash = False
    for char in topic.strip().lower():
        if char.isalnum():
            slug_chars.append(char)
            last_dash = False
            continue
        if not last_dash:
            slug_chars.append("-")
            last_dash = True
    slug = "".join(slug_chars).strip("-")
    return slug or "topic"


def _default_topic_from_dir(wiki_dir: Path) -> str:
    """Create a display topic from a directory name."""
    return wiki_dir.name.replace("-", " ").replace("_", " ").strip().title() or wiki_dir.name


def _build_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="LLM wiki (Deep Agents + Local directory)"
    )
    parser.add_argument(
        "--mode", required=True, choices=["init", "ingest", "query", "lint"]
    )
    parser.add_argument(
        "--wiki-dir",
        required=True,
        help="Local wiki directory containing wiki files",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="The topic name of the wiki (defaults to the name of the wiki directory)",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Source file or directory for ingest mode (repeatable)",
    )
    parser.add_argument(
        "--note", default=None, help="Optional note to include in ingest/lint prompt"
    )
    parser.add_argument(
        "--question", default=None, help="Question to answer in query mode"
    )
    parser.add_argument(
        "--model", default=None, help="Optional model override for create_deep_agent"
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="Opt in to ingest review/confirmation before applying wiki updates",
    )
    return parser


def parse_config(argv: Sequence[str] | None = None) -> RunnerConfig:
    """Parse CLI arguments into a runner config."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    mode = args.mode
    if mode == "ingest" and not args.source:
        parser.error("--source is required in ingest mode")
    if mode == "query" and not args.question:
        parser.error("--question is required in query mode")

    wiki_dir = Path(args.wiki_dir).expanduser().resolve()
    topic = args.topic or _default_topic_from_dir(wiki_dir)

    return RunnerConfig(
        mode=mode,
        topic=topic,
        wiki_dir=wiki_dir,
        sources=tuple(Path(source).expanduser().resolve() for source in args.source),
        note=args.note,
        question=args.question,
        model=args.model,
        review=bool(args.review),
    )


def _iter_tree_paths(root_dir: Path) -> Iterator[Path]:
    """Yield all paths rooted under a workspace directory."""
    yield root_dir
    for current_root, dirnames, filenames in os.walk(
            root_dir, topdown=True, followlinks=False
    ):
        parent = Path(current_root)
        for dirname in dirnames:
            yield parent / dirname
        for filename in filenames:
            yield parent / filename


def _ensure_no_symlinks(root_dir: Path) -> None:
    """Reject workspace trees that contain symlinks."""
    for path in _iter_tree_paths(root_dir):
        if not path.is_symlink():
            continue
        with suppress(ValueError):
            relative = path.relative_to(root_dir)
            msg = (
                "Symlinks are not supported in wiki workspaces for security reasons: "
                f"{relative}"
            )
            raise WikiError(msg)
        msg = f"Symlinks are not supported in wiki workspaces for security reasons: {path}"
        raise WikiError(msg)


def _safe_write_text(path: Path, content: str, *, append: bool = False) -> None:
    """Write UTF-8 text while refusing symlink targets."""
    if path.is_symlink():
        msg = f"Refusing to write to symlink path: {path}"
        raise WikiError(msg)

    flags = os.O_WRONLY | os.O_CREAT
    if append:
        flags |= os.O_APPEND
    else:
        flags |= os.O_TRUNC

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow

    try:
        descriptor = os.open(path, flags, 0o644)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = f"Refusing to write to symlink path: {path}"
            raise WikiError(msg) from exc
        raise

    mode = "a" if append else "w"
    with os.fdopen(descriptor, mode, encoding="utf-8") as handle:
        handle.write(content)


def _write_if_missing(path: Path, content: str) -> None:
    """Write file content only when the target does not already exist."""
    if path.is_symlink():
        msg = f"Refusing to write to symlink path: {path}"
        raise WikiError(msg)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe_write_text(path, content)


def _agents_md(topic: str) -> str:
    """Build default AGENTS.md guidance content."""
    return (
        f"# {topic} Wiki\n\n"
        "Use this file as the wiki schema/config for agent behavior.\n"
        "Keep it concise and co-evolve it as the wiki and workflow change.\n\n"
        "Rules:\n"
        "- Treat `/raw/` as read-only source material.\n"
        "- Ingest flow should be supervised: review takeaways first, then apply updates.\n"
        "- Ingest updates should prioritize canonical concept/entity/theme pages.\n"
        "- Prefer a flat `/wiki/` layout by default; create subdirectories only when they clearly improve organization.\n"
        "- Use `/log.md` as recency context and keep it append-only.\n"
        "- Do not edit `/log.md` directly; the runner appends structured timeline entries.\n"
        "- Keep `/wiki/index.md` current as a content catalog.\n"
    )


def _ensure_scaffold(
        topic_dir: Path, topic: str, *, overwrite_agents: bool = False
) -> None:
    """Ensure required topic workspace files and directories exist."""
    (topic_dir / "raw").mkdir(parents=True, exist_ok=True)
    (topic_dir / "wiki").mkdir(parents=True, exist_ok=True)
    _write_if_missing(
        topic_dir / "wiki" / "index.md",
        index_helpers.empty_index_text(topic),
    )
    _write_if_missing(topic_dir / "log.md", "# Change Log\n")

    agents_path = topic_dir / "AGENTS.md"
    if overwrite_agents or not agents_path.exists():
        _safe_write_text(agents_path, _agents_md(topic))


def _validate_text_only_directory(root_dir: Path) -> None:
    """Validate that all files in a directory are UTF-8 text with allowed suffixes."""
    _ensure_no_symlinks(root_dir)
    for file_path in root_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in _ALLOWED_TEXT_SUFFIXES:
            rel = file_path.relative_to(root_dir)
            msg = (
                f"Unsupported file for v1 text-only hub pushes: {rel}. "
                "Allowed extensions: md, txt, json, yaml, yml, csv."
            )
            raise WikiError(msg)
        try:
            file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            rel = file_path.relative_to(root_dir)
            msg = f"File {rel} is not valid UTF-8 text. Binary uploads are not supported in v1."
            raise WikiError(msg) from exc


def _extract_pdf_text(file_path: Path) -> str:
    """Extract PDF content as markdown, falling back to pypdf text extraction if needed."""
    try:
        import pymupdf4llm
        markdown_content = pymupdf4llm.to_markdown(str(file_path))
        if isinstance(markdown_content, list):
            return "\n\n".join(str(item) for item in markdown_content)
        if markdown_content.strip():
            return markdown_content
    except Exception:
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            page_texts: list[str] = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    page_texts.append(f"## Page {index}:\n\n{text}")
            return "\n\n".join(page_texts)
        except Exception as e:
            return f"Error extracting PDF text: {e}"
    return ""


def _stage_sources(sources: Sequence[Path], workspace_dir: Path) -> list[Path]:
    """Copy and de-duplicate source files into the workspace raw directory."""
    staged: list[Path] = []
    raw_dir = workspace_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        if not source.exists() or not source.is_file():
            msg = f"Source file not found: {source}"
            raise WikiError(msg)

        if source.suffix.lower() not in _ALLOWED_SOURCE_SUFFIXES:
            msg = (
                f"Unsupported source file type for {source}. "
                f"Use files with extensions: {', '.join(sorted(ext.strip('.') for ext in _ALLOWED_SOURCE_SUFFIXES))}."
            )
            raise WikiError(msg)

        is_pdf = source.suffix.lower() == ".pdf"

        if is_pdf:
            text = _extract_pdf_text(source)
            destination = raw_dir / f"{source.name}.md"
            suffix = ".md"
            stem = f"{source.stem}.pdf"
        else:
            try:
                text = source.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                msg = f"Source file must be UTF-8 text: {source}"
                raise WikiError(msg) from exc
            destination = raw_dir / source.name
            suffix = source.suffix
            stem = source.stem

        counter = 2
        while destination.exists() or destination.is_symlink():
            destination = raw_dir / f"{stem}-{counter}{suffix}"
            counter += 1

        _safe_write_text(destination, text)
        staged.append(destination)

    return staged


def _extract_text(content: object) -> str:
    """Extract textual content from agent message payloads."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return str(content)


def _extract_final_ai_message(result: dict[str, object]) -> str:
    """Return the final assistant text message from an agent invoke result."""
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        msg_type = getattr(message, "type", None)
        if msg_type is None and isinstance(message, dict):
            msg_type = message.get("type")
        if msg_type not in {"ai", "assistant"}:
            continue

        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        text = _extract_text(content).strip()
        if text:
            return text
    return ""


def _refresh_index(topic: str, workspace_dir: Path) -> None:
    """Rebuild the wiki index page from current markdown pages."""
    index_helpers.refresh_index(topic, workspace_dir, write_text=_safe_write_text)


def _append_log_entry(
        workspace_dir: Path,
        phase: str,
        outcome: str,
        *,
        metadata: dict[str, object] | None = None,
        summary: str | None = None,
) -> None:
    """Append one structured, parseable interaction entry to the wiki log."""
    log_helpers.append_log_entry(
        workspace_dir,
        phase,
        outcome,
        metadata=metadata,
        summary=summary,
        ensure_file=_write_if_missing,
        append_text=lambda path, content: _safe_write_text(path, content, append=True),
    )


def _permissions() -> list[FilesystemPermission]:
    """Define filesystem write policy for wiki operations."""
    return [
        FilesystemPermission(operations=["write"], paths=["/raw/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/AGENTS.md"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/wiki/**"], mode="allow"),
        FilesystemPermission(operations=["write"], paths=["/log.md"], mode="deny"),
    ]


def _review_permissions() -> list[FilesystemPermission]:
    """Define filesystem policy for ingest review (read-only over wiki/raw)."""
    return [
        FilesystemPermission(operations=["write"], paths=["/raw/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/wiki/**"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/log.md"], mode="deny"),
        FilesystemPermission(operations=["write"], paths=["/AGENTS.md"], mode="deny"),
    ]


@contextmanager
def _create_local_sandbox_backend(workspace_dir: Path) -> Iterator[SandboxBackendProtocol]:
    """Create a local shell-backed execution backend."""
    yield LocalShellBackend(root_dir=workspace_dir, virtual_mode=False)


def _run_agent_mode(
        workspace_dir: Path,
        topic: str,
        prompt: str,
        model: str | None,
        *,
        permissions: list[FilesystemPermission],
) -> str:
    """Execute one agent operation against the pulled workspace."""
    with _create_local_sandbox_backend(workspace_dir) as sandbox_backend:
        workspace_backend = FilesystemBackend(root_dir=workspace_dir, virtual_mode=True)
        backend = CompositeBackend(
            default=sandbox_backend,
            routes={
                "/raw/": workspace_backend,
                "/wiki/": workspace_backend,
                "/log.md": workspace_backend,
                "/AGENTS.md": workspace_backend,
            },
        )
        model_arg = model if model is not None else _resolve_model()
        agent = create_deep_agent(
            model=model_arg,
            backend=backend,
            permissions=permissions,
            system_prompt=_BASE_SYSTEM_PROMPT,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})

    text = _extract_final_ai_message(result)
    if text:
        return text
    return f"Completed {topic} wiki operation."


def _run_agent_apply_mode(
        workspace_dir: Path, topic: str, prompt: str, model: str | None
) -> str:
    """Run a mutating agent operation against wiki files."""
    return _run_agent_mode(
        workspace_dir,
        topic,
        prompt,
        model,
        permissions=_permissions(),
    )


def _run_agent_review_mode(
        workspace_dir: Path, topic: str, prompt: str, model: str | None
) -> str:
    """Run a read-only ingest review operation."""
    return _run_agent_mode(
        workspace_dir,
        topic,
        prompt,
        model,
        permissions=_review_permissions(),
    )


def _run_init(config: RunnerConfig, deps: CliDeps) -> RunResult:
    """Initialize a local topic repo directory layout."""
    from init import run_init

    return run_init(config, deps)


def _collect_directory_sources(directory: Path) -> list[Path]:
    """Collect allowed file paths from a source directory recursively."""
    from ingest import collect_directory_sources

    return collect_directory_sources(directory)


def _expand_sources(sources: Sequence[Path]) -> list[Path]:
    """Expand source arguments into a deterministic list of file paths."""
    from ingest import expand_sources

    return expand_sources(sources)


def _build_ingest_review_prompt(
        topic: str, staged_paths: Sequence[Path], note: str | None
) -> str:
    """Build the ingest review prompt for staged source material."""
    from ingest import build_ingest_review_prompt

    return build_ingest_review_prompt(topic, staged_paths, note)


def _build_ingest_apply_prompt(
        topic: str,
        staged_paths: Sequence[Path],
        review_summary: str,
        note: str | None,
) -> str:
    """Build the ingest apply prompt after operator approval."""
    from ingest import build_ingest_apply_prompt

    return build_ingest_apply_prompt(topic, staged_paths, review_summary, note)


def _confirm_ingest_apply(review: str, ask_user: Callable[[str], str]) -> bool:
    """Ask operator to approve ingest apply after the review phase."""
    from ingest import confirm_ingest_apply

    return confirm_ingest_apply(review, ask_user)


def _run_ingest_workspace(
        config: RunnerConfig, workspace_dir: Path, deps: CliDeps
) -> IngestResult:
    """Run ingest mode against a pulled workspace directory."""
    from ingest import run_ingest_workspace

    return run_ingest_workspace(config, workspace_dir, deps)


def _run_local_mode(config: RunnerConfig, deps: CliDeps) -> RunResult:
    """Run the selected mode directly on the local wiki directory."""
    workspace_dir = config.wiki_dir

    _ensure_no_symlinks(workspace_dir)
    _ensure_scaffold(workspace_dir, config.topic)

    if config.mode == "ingest":
        ingest_result = _run_ingest_workspace(config, workspace_dir, deps)
        answer = ingest_result.answer
    elif config.mode == "query":
        from query import run_query_workspace

        query_result = run_query_workspace(config, workspace_dir, deps)
        answer = query_result.answer
    else:
        from lint import run_lint_workspace

        answer = run_lint_workspace(config, workspace_dir, deps)

    return RunResult(answer=answer)


def run(config: RunnerConfig, deps: CliDeps | None = None) -> RunResult:
    """Execute the requested wiki workflow."""
    resolved_deps = deps or CliDeps(
        run_agent_mode=_run_agent_apply_mode,
        run_agent_review_mode=_run_agent_review_mode,
        ask_user=input,
        tempdir_factory=tempfile.TemporaryDirectory,
    )

    if config.mode == "init":
        return _run_init(config, resolved_deps)
    return _run_local_mode(config, resolved_deps)


__all__ = [
    "CliDeps",
    "RunResult",
    "RunnerConfig",
    "WikiError",
    "parse_config",
    "run",
]
