"""Core wiki operations service for thread-level RAG.

Ports llm-wiki's init, ingest, query, and lint workflows as direct Python APIs
(no CLI). Each operation runs against a per-thread wiki workspace at
``./docs/threads-wiki/<thread-id>/`` using the ``deepagents`` library.

Cancellation
------------
Long-running ingest operations check ``cancel_event`` between phases.
When the event is set the coroutine raises ``asyncio.CancelledError`` so
the background task terminates promptly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import sys

from .models import (
    IngestPhase,
    IngestProgress,
    ThreadWikiPaths,
    WikiQueryResult,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Text-based formats: read directly with read_text().
_ALLOWED_TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
# Binary formats: require content_extractors for text extraction.
_BINARY_EXTRACT_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx"}
# All supported source types.
_ALLOWED_SOURCE_SUFFIXES = _ALLOWED_TEXT_SUFFIXES | _BINARY_EXTRACT_SUFFIXES

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


# ── Scaffold helpers (ported from llm-wiki helpers.py) ───────────────────────

def _slugify(text: str) -> str:
    """Convert text into a stable URL-friendly slug."""
    slug_chars: list[str] = []
    last_dash = False
    for char in text.strip().lower():
        if char.isalnum():
            slug_chars.append(char)
            last_dash = False
        elif not last_dash:
            slug_chars.append("-")
            last_dash = True
    slug = "".join(slug_chars).strip("-")
    return slug or "topic"


def _empty_index_text(topic: str) -> str:
    """Build default index markdown for an empty wiki."""
    lines = [
        f"# {topic} Wiki",
        "",
        "Content catalog for wiki navigation and retrieval.",
        "Read this page first during query workflows.",
        "",
        "## Other Pages",
        "",
        "- _No pages yet._",
    ]
    return "\n".join(lines) + "\n"


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


def _write_if_missing(path: Path, content: str) -> None:
    """Write file content only when the target does not already exist."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_scaffold(wiki_dir: Path, topic: str) -> None:
    """Ensure the required wiki workspace files and directories exist."""
    (wiki_dir / "raw").mkdir(parents=True, exist_ok=True)
    (wiki_dir / "wiki").mkdir(parents=True, exist_ok=True)
    _write_if_missing(wiki_dir / "wiki" / "index.md", _empty_index_text(topic))
    _write_if_missing(wiki_dir / "log.md", "# Change Log\n")
    _write_if_missing(wiki_dir / "AGENTS.md", _agents_md(topic))


# ── Source staging ────────────────────────────────────────────────────────────

def _extract_binary_source(file_path: Path) -> str:
    """Extract text from a binary document using content_extractors.

    Supports PDF, DOCX, PPTX, and XLSX formats. Falls back to a graceful
    error message if extraction fails rather than raising.
    """
    try:
        from research_agent.utils.content_extractors import extract_supported_document
        return extract_supported_document(file_path)
    except ImportError:
        # content_extractors not available; fall back to minimal PDF extraction.
        if file_path.suffix.lower() == ".pdf":
            return _fallback_pdf_extract(file_path)
        return f"Error: content_extractors module unavailable for {file_path.suffix}"
    except Exception as exc:
        return f"Error extracting {file_path.suffix}: {exc}"


def _fallback_pdf_extract(file_path: Path) -> str:
    """Minimal PDF extraction fallback when content_extractors is unavailable."""
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


def _stage_sources(source_paths: list[Path], raw_dir: Path) -> list[Path]:
    """Copy source files into the wiki's raw directory, de-duplicating.

    Text-based formats (.md, .txt, .json, .yaml, .yml, .csv) are read directly.
    Binary formats (.pdf, .docx, .pptx, .xlsx) are extracted to markdown/text
    via ``content_extractors`` and saved as ``.md`` in the raw directory.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []

    for source in source_paths:
        if not source.exists() or not source.is_file():
            logger.warning("Source file not found, skipping: %s", source)
            continue

        suffix = source.suffix.lower()
        if suffix not in _ALLOWED_SOURCE_SUFFIXES:
            logger.warning("Unsupported source type (%s), skipping: %s", suffix, source)
            continue

        is_binary = suffix in _BINARY_EXTRACT_SUFFIXES
        if is_binary:
            text = _extract_binary_source(source)
            destination = raw_dir / f"{source.name}.md"
            out_suffix = ".md"
            stem = f"{source.stem}.{suffix.lstrip('.')}"
        else:
            try:
                text = source.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("Non-UTF-8 source, skipping: %s", source)
                continue
            destination = raw_dir / source.name
            out_suffix = source.suffix
            stem = source.stem

        counter = 2
        while destination.exists():
            destination = raw_dir / f"{stem}-{counter}{out_suffix}"
            counter += 1

        destination.write_text(text, encoding="utf-8")
        staged.append(destination)

    return staged


# ── Index refresh ─────────────────────────────────────────────────────────────

_INDEX_CATEGORY_ORDER = (
    "Entities", "Concepts", "Sources", "Timelines", "Queries", "Syntheses", "Other Pages",
)
_INDEX_DIRECTORY_CATEGORIES = {
    "entity": "Entities", "entities": "Entities",
    "concept": "Concepts", "concepts": "Concepts",
    "source": "Sources", "sources": "Sources",
    "timeline": "Timelines", "timelines": "Timelines",
    "query": "Queries", "queries": "Queries",
    "synthesis": "Syntheses", "syntheses": "Syntheses",
}
_INDEX_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _strip_markdown_inline(text: str) -> str:
    stripped = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    stripped = re.sub(r"`([^`]+)`", r"\1", stripped)
    stripped = re.sub(r"[*_~]", "", stripped)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip(" -:")


def _refresh_index(topic: str, wiki_dir: Path) -> None:
    """Rebuild wiki/index.md from current markdown pages."""
    wiki_content_dir = wiki_dir / "wiki"
    pages = [p for p in sorted(wiki_content_dir.rglob("*.md")) if p.name != "index.md"]

    if not pages:
        (wiki_content_dir / "index.md").write_text(_empty_index_text(topic), encoding="utf-8")
        return

    section_lines: dict[str, list[str]] = {cat: [] for cat in _INDEX_CATEGORY_ORDER}
    for page in pages:
        relative = page.relative_to(wiki_content_dir).as_posix()
        content = page.read_text(encoding="utf-8")

        # Extract title
        title = page.stem.replace("-", " ").replace("_", " ").strip().title()
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = _strip_markdown_inline(stripped.lstrip("#").strip())
                if heading:
                    title = heading
                    break

        # Extract summary
        summary = "No summary available."
        in_code = False
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_code = not in_code
                continue
            if in_code or not s or s.startswith("#"):
                continue
            candidate = _strip_markdown_inline(s.lstrip("-*+ ").strip())
            if candidate:
                summary = candidate[:147] + "..." if len(candidate) > 150 else candidate
                break

        # Category
        parts = page.relative_to(wiki_content_dir).parts
        cat = _INDEX_DIRECTORY_CATEGORIES.get(parts[0].lower(), "Other Pages") if len(parts) > 1 else "Other Pages"

        entry = f"- [{title}]({relative}) - {summary}"
        section_lines[cat].append(entry)

    lines = [f"# {topic} Wiki", "", "Content catalog for wiki navigation and retrieval.",
             "Read this page first during query workflows.", ""]
    for cat in _INDEX_CATEGORY_ORDER:
        if section_lines[cat]:
            lines.extend([f"## {cat}", ""])
            lines.extend(section_lines[cat])
            lines.append("")

    (wiki_content_dir / "index.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


# ── Log helpers ───────────────────────────────────────────────────────────────

def _append_log_entry(wiki_dir: Path, phase: str, outcome: str, *, summary: str = "") -> None:
    """Append a structured entry to the wiki's log.md."""
    from datetime import UTC, datetime
    log_path = wiki_dir / "log.md"
    if not log_path.exists():
        log_path.write_text("# Change Log\n", encoding="utf-8")

    now = datetime.now(UTC)
    date_text = now.strftime("%Y-%m-%d")
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    summary_text = summary[:320] if summary else "No summary provided."

    entry = (
        f"\n## [{date_text}] {phase} | outcome={outcome}\n"
        f"- timestamp: {timestamp}\n"
        f"- summary: {summary_text}\n"
    )
    with log_path.open("a", encoding="utf-8") as f:
        f.write(entry)


# ── Agent execution ───────────────────────────────────────────────────────────

def _resolve_model():
    """Return the configured chat model from model_factory."""
    # Import here to avoid circular imports at module load time.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from model_factory import get_configured_model
        return get_configured_model()
    finally:
        sys.path.pop(0)


def _run_agent(wiki_dir: Path, prompt: str, *, read_only: bool = False) -> str:
    """Execute one deepagents pass against the wiki workspace.

    Args:
        wiki_dir: Root of the wiki workspace (contains raw/, wiki/, log.md, AGENTS.md).
        prompt: The instruction prompt to send to the agent.
        read_only: If True, deny all write permissions (review-only mode).
    """
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend, FilesystemBackend, LocalShellBackend
    from deepagents.middleware.filesystem import FilesystemPermission

    sandbox_backend = LocalShellBackend(root_dir=wiki_dir, virtual_mode=False)
    workspace_backend = FilesystemBackend(root_dir=wiki_dir, virtual_mode=True)
    backend = CompositeBackend(
        default=sandbox_backend,
        routes={
            "/raw/": workspace_backend,
            "/wiki/": workspace_backend,
            "/log.md": workspace_backend,
            "/AGENTS.md": workspace_backend,
        },
    )

    if read_only:
        permissions = [
            FilesystemPermission(operations=["write"], paths=["/raw/**"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/wiki/**"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/log.md"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/AGENTS.md"], mode="deny"),
        ]
    else:
        permissions = [
            FilesystemPermission(operations=["write"], paths=["/raw/**"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/AGENTS.md"], mode="deny"),
            FilesystemPermission(operations=["write"], paths=["/wiki/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/log.md"], mode="deny"),
        ]

    model = _resolve_model()
    agent = create_deep_agent(
        model=model,
        backend=backend,
        permissions=permissions,
        system_prompt=_BASE_SYSTEM_PROMPT,
    )
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})

    # Extract the final AI text message.
    messages = result.get("messages", [])
    for message in reversed(messages):
        msg_type = getattr(message, "type", None)
        if msg_type is None and isinstance(message, dict):
            msg_type = message.get("type")
        if msg_type not in {"ai", "assistant"}:
            continue
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            text = "".join(parts).strip()
            if text:
                return text

    return "Completed wiki operation."


# ── Prompt builders ───────────────────────────────────────────────────────────

def _build_ingest_review_prompt(topic: str, staged_names: list[str], note: str | None) -> str:
    """Build the ingest review prompt (read-only analysis pass)."""
    source_block = "\n".join(f"- /raw/{name}" for name in staged_names)
    note_block = note or "(none)"
    return (
        f"Review the staged sources for topic '{topic}' and prepare a deep ingest plan.\n\n"
        "Phase constraint: review-only. Do not create, edit, move, or delete files yet.\n\n"
        "Analysis standards:\n"
        "- Read every staged source before proposing wiki edits.\n"
        "- Distinguish direct evidence from inference.\n"
        "- Prefer canonical page updates over creating fragmented pages.\n"
        "- Preserve uncertainty; do not invent unsupported claims.\n"
        "- Use source filename citations for non-trivial claims.\n\n"
        "Required output format (markdown):\n"
        "## 1) Source-by-source extraction\n"
        "## 2) Proposed wiki change set\n"
        "## 3) Cross-source synthesis and structure\n"
        "## 4) Contradictions and unresolved claims\n"
        "## 5) Index updates and recency notes\n"
        "## 6) Gaps and follow-up questions\n\n"
        f"Staged sources:\n{source_block}\n\n"
        f"Operator note: {note_block}\n"
    )


def _build_ingest_apply_prompt(topic: str, staged_names: list[str], review_summary: str, note: str | None) -> str:
    """Build the ingest apply prompt (mutating pass)."""
    source_block = "\n".join(f"- /raw/{name}" for name in staged_names)
    note_block = note or "(none)"
    return (
        f"Apply an approved ingest update for topic '{topic}'.\n\n"
        "Required workflow:\n"
        "1) Read all staged files in `/raw/` before editing wiki content.\n"
        "2) Update canonical concept/entity/theme pages with high-signal evidence.\n"
        "3) Integrate cross-source synthesis, not just per-source summaries.\n"
        "4) Mark contradictions explicitly and preserve unresolved uncertainty.\n"
        "5) Update `/wiki/index.md`.\n"
        "6) Do not edit `/log.md`.\n"
        "7) Never write to `/raw/`.\n\n"
        "Writing standards:\n"
        "- Keep pages scannable with clear headings and concise prose.\n"
        "- Use source filename citations for non-trivial claims.\n"
        "- Avoid duplicative pages; merge into canonical pages when possible.\n\n"
        "Return a concise apply report:\n"
        "A) Files created  B) Files updated  C) Key synthesis  D) Remaining uncertainties\n\n"
        f"Approved review plan:\n{review_summary}\n\n"
        f"Staged sources:\n{source_block}\n\n"
        f"Operator note: {note_block}\n"
    )


def _build_query_prompt(topic: str, question: str) -> str:
    """Build the read-only query prompt."""
    return (
        f"Answer this question about '{topic}': {question}\n\n"
        "This is analysis-only. Do not create, edit, move, or delete files.\n\n"
        "Required workflow:\n"
        "1) Read `/wiki/index.md` first and use its categorized summaries to choose candidate pages.\n"
        "2) Read recent `/log.md` entries (latest ~10 `## [` headings) to understand what was ingested recently.\n"
        "3) Prefer checking relevant prior `/wiki/query/*.md` pages first.\n"
        "4) Read the canonical wiki pages before final synthesis.\n"
        "5) Provide a grounded answer with wiki file path citations.\n"
        "6) Decide whether this answer should be filed as a durable wiki page.\n\n"
        "Output format (exact keys):\n"
        "ANSWER:\n<markdown answer with citations>\n\n"
        "FILING_DECISION: file|skip\n"
        "FILING_REASON: <one sentence>\n"
    )


def _build_lint_prompt(topic: str, note: str | None) -> str:
    """Build the lint reconciliation prompt."""
    note_text = note or "(none)"
    return (
        f"Run a single-pass lint reconciliation for the '{topic}' wiki under `/wiki/`.\n\n"
        "Execution mode:\n"
        "- Read recent `/log.md` entries first.\n"
        "- Apply updates immediately (no review/confirm phase).\n"
        "- You may create new canonical wiki pages when required for reconciliation.\n"
        "- Do not edit `/log.md`.\n"
        "- Never write to `/raw/`.\n\n"
        "Required health checks and fixes:\n"
        "- Reconcile contradictions across wiki pages.\n"
        "- Identify stale claims superseded by newer evidence.\n"
        "- Detect orphan pages with no inbound links and add/repair cross-references.\n"
        "- When an important concept lacks a dedicated page, create a canonical page.\n"
        "- Identify docs gaps and missing evidence.\n\n"
        "After edits, return a concise report:\n"
        "## Reconciled Changes\n## Remaining Gaps\n## Suggested Next Questions and Sources\n\n"
        f"Operator note: {note_text}\n"
    )


# ── Query decision parsing ────────────────────────────────────────────────────

_DECISION_RE = re.compile(r"^FILING_DECISION:\s*(file|skip)\s*$", re.IGNORECASE | re.MULTILINE)
_REASON_RE = re.compile(r"^FILING_REASON:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _parse_query_decision(raw: str) -> tuple[str, bool, str]:
    """Parse answer, should_file, and reason from raw query response."""
    decision_match = _DECISION_RE.search(raw)
    reason_match = _REASON_RE.search(raw)

    should_file = decision_match is not None and decision_match.group(1).lower() == "file"
    reason = reason_match.group(1).strip() if reason_match else "Decision marker missing."

    answer = raw
    if decision_match:
        answer = raw[: decision_match.start()].strip()
    if answer.upper().startswith("ANSWER:"):
        answer = answer[len("ANSWER:"):].strip()
    if not answer:
        answer = raw or "No answer returned."

    return answer, should_file, reason


# ── Public service API ────────────────────────────────────────────────────────

async def init_wiki(paths: ThreadWikiPaths, topic: str) -> None:
    """Initialize the wiki workspace scaffold for a thread."""
    await asyncio.to_thread(paths.wiki_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(_ensure_scaffold, paths.wiki_dir, topic)
    logger.info("Initialized wiki workspace at %s", paths.wiki_dir)


def _collect_source_files(docs_dir: Path) -> list[Path]:
    """Collect all ingestable files from a thread's docs directory."""
    if not docs_dir.exists():
        return []
    return [p for p in sorted(docs_dir.rglob("*")) if p.is_file()]


async def run_ingest(
        paths: ThreadWikiPaths,
        topic: str,
        progress: IngestProgress,
        cancel_event: asyncio.Event,
        note: str | None = None,
) -> str:
    """Run the full ingest workflow with progress tracking and cancellation.

    Phases:
    1. Initialize scaffold
    2. Stage source files from docs_dir → raw/
    3. LLM review/analysis pass (read-only)
    4. LLM apply pass (mutating)
    5. Refresh index

    Returns the apply summary text.
    """
    try:
        # Phase 1: Initialize
        progress.advance(IngestPhase.INITIALIZING, "Creating wiki scaffold...")
        await init_wiki(paths, topic)

        await check_cancellation(cancel_event, phase_name="initializing")

        # Phase 2: Stage sources
        progress.advance(IngestPhase.STAGING_SOURCES, "Collecting and staging source files...")
        source_files = await asyncio.to_thread(_collect_source_files, paths.docs_dir)
        progress.source_count = len(source_files)

        if not source_files:
            progress.mark_complete("No source files found to ingest.")
            return "No source files found."

        staged = await asyncio.to_thread(_stage_sources, source_files, paths.raw_dir)
        staged_names = [p.name for p in staged]
        progress.sources_processed = len(staged)

        await check_cancellation(cancel_event, phase_name="staging_sources")

        # Phase 3: Review (read-only LLM analysis)
        progress.advance(IngestPhase.ANALYZING, f"Analyzing {len(staged)} sources...")
        review_prompt = _build_ingest_review_prompt(topic, staged_names, note)
        review_summary = await asyncio.to_thread(
            _run_agent, paths.wiki_dir, review_prompt, read_only=True
        )
        _append_log_entry(
            paths.wiki_dir, "ingest.review", "completed",
            summary=f"Reviewed {len(staged)} sources.",
        )

        await check_cancellation(cancel_event, phase_name="analyzing")

        # Phase 4: Apply (mutating LLM pass)
        progress.advance(IngestPhase.APPLYING, "Applying wiki updates...")
        apply_prompt = _build_ingest_apply_prompt(topic, staged_names, review_summary, note)
        apply_result = await asyncio.to_thread(
            _run_agent, paths.wiki_dir, apply_prompt, read_only=False
        )
        _append_log_entry(
            paths.wiki_dir, "ingest.apply", "applied",
            summary=apply_result[:320],
        )

        await check_cancellation(cancel_event, phase_name="applying")

        # Phase 5: Refresh index
        progress.advance(IngestPhase.REFRESHING_INDEX, "Rebuilding wiki index...")
        await asyncio.to_thread(_refresh_index, topic, paths.wiki_dir)

        progress.mark_complete(f"Ingested {len(staged)} sources successfully.")
        return apply_result

    except asyncio.CancelledError:
        progress.mark_cancelled()
        _append_log_entry(paths.wiki_dir, "ingest", "cancelled", summary="Ingest cancelled by client.")
        raise
    except Exception as exc:
        progress.mark_error(str(exc))
        _append_log_entry(paths.wiki_dir, "ingest", "error", summary=str(exc)[:320])
        logger.exception("Ingest failed for thread %s", paths.thread_id)
        raise


async def run_query(
        paths: ThreadWikiPaths,
        topic: str,
        question: str,
        *,
        file_results: bool = True,
) -> WikiQueryResult:
    """Query the thread's wiki knowledge base.

    Returns a grounded answer with optional filing into wiki/query/.
    """
    query_prompt = _build_query_prompt(topic, question)
    raw_response = await asyncio.to_thread(
        _run_agent, paths.wiki_dir, query_prompt, read_only=True
    )
    answer, should_file, reason = _parse_query_decision(raw_response)

    _append_log_entry(
        paths.wiki_dir, "query.review",
        "file" if should_file else "skip",
        summary=answer[:320],
    )

    filed_path: str | None = None
    if should_file and file_results:
        slug = _slugify(question)[:80].rstrip("-") or "query"
        target = f"/wiki/query/{slug}.md"
        file_prompt = (
            f"File a durable query answer for topic '{topic}'.\n\n"
            f"Create or overwrite exactly: `{target}`\n\n"
            "Requirements:\n"
            "1) Write a clean, scannable markdown page.\n"
            "2) Preserve grounded claims and include wiki file path citations.\n"
            "3) Include sections: Question, Answer, and Sources.\n"
            "4) Never write to `/raw/`.\n\n"
            f"Filing reason: {reason}\n\nQuestion: {question}\n\nAnswer draft:\n{answer}\n"
        )
        await asyncio.to_thread(_run_agent, paths.wiki_dir, file_prompt, read_only=False)
        _refresh_index(topic, paths.wiki_dir)
        _append_log_entry(
            paths.wiki_dir, "query.apply", "filed",
            summary=f"Filed query answer at {target}.",
        )
        filed_path = target

    # Extract cited source paths from the answer text.
    cited = re.findall(r"/raw/([A-Za-z0-9._/\-]+)", answer)

    return WikiQueryResult(answer=answer, filed_path=filed_path, sources_cited=cited)


async def run_lint(
        paths: ThreadWikiPaths,
        topic: str,
        note: str | None = None,
) -> str:
    """Run lint reconciliation on the thread's wiki.

    Use this after document deletions to reconcile stale references.
    """
    lint_prompt = _build_lint_prompt(topic, note)
    result = await asyncio.to_thread(
        _run_agent, paths.wiki_dir, lint_prompt, read_only=False
    )
    await asyncio.to_thread(_refresh_index, topic, paths.wiki_dir)
    _append_log_entry(paths.wiki_dir, "lint.apply", "applied", summary=result[:320])
    return result


async def check_cancellation(cancel_event: asyncio.Event, *, phase_name: str = "") -> None:
    """Raise CancelledError if cancellation was requested."""
    if cancel_event.is_set():
        raise asyncio.CancelledError(
            f"Ingest cancelled{' during ' + phase_name if phase_name else ''}."
        )
