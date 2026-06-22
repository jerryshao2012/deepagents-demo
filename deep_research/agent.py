import asyncio
import concurrent.futures
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import sys
import time
from deepagents import create_deep_agent, SubAgent
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemState
from dotenv import load_dotenv
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig

from logger_utils import setup_logger
from model_factory import get_configured_model
from research_agent import (
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from research_agent.prompts import RESEARCHER_DESCRIPTION
from research_agent.tools import (
    normalize_path_for_filesystem_tools,
    think_tool,
    render_skill_output,
    finalize_golden_dataset_output,
    ls,
    glob,
    read_file,
    read_doc_folder,
    write_file,
    tavily_search,
    fetch_webpage_content,
)
from research_agent.utils.cli import (
    build_instruction,
)
from research_agent.utils.eval_tracking import log_server_metrics
from research_agent.utils.skill_registry import get_skill_registry
from thread_wiki.models import ThreadWikiPaths, WikiQueryResult
from thread_wiki.service import run_query
from utils import get_ssl_verify_config, str2bool

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)

# Create SSL verification setting - CLI flag takes precedence over env var
verify_ssl = get_ssl_verify_config()

# Limits - configurable via environment variables
MAX_CONCURRENT_RESEARCH_UNITS = int(os.environ.get("MAX_CONCURRENT_RESEARCH_UNITS", "3"))
MAX_RESEARCHER_ITERATIONS = int(os.environ.get("MAX_RESEARCHER_ITERATIONS", "3"))

# Evaluation tracking - configurable via environment variables
ENABLE_EVAL_TRACKING = str2bool(os.environ.get("ENABLE_EVAL_TRACKING"), False)
EVAL_HISTORY_FILE = os.environ.get("EVAL_HISTORY_FILE", "./output/eval_history/server_runs.jsonl")

# Get current date
current_date = datetime.now().strftime("%Y-%m-%d")

# Initialize dynamic skill registry (use singleton to avoid duplicate initialization)
skill_registry = get_skill_registry()


class ResearchState(FilesystemState):
    """Runtime state for the research agent."""
    doc_folder: str | None
    skill: str | None
    no_web: bool | None
    chat_start_time: float | None
    chat_elapsed_seconds: float | None
    _eval_logged: bool


class ResearchStateMiddleware(AgentMiddleware):
    """Middleware to configure state variables like DOC_FOLDER before the agent runs."""

    # Ensure middleware state update are validated against the standard state schema.
    state_schema = ResearchState

    @staticmethod
    def _get_current_user_message(messages: list) -> str | None:
        """Return the content of the **last** user/human message in the list."""
        last_user_content: str | None = None
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "user":
                last_user_content = str(m.get("content", ""))
            elif hasattr(m, "type") and getattr(m, "type", None) == "human":
                last_user_content = str(getattr(m, "content", ""))
        return last_user_content

    @staticmethod
    def _seed_research_request_file(user_message: str | None, state: ResearchState) -> dict[str, Any]:
        """Make the current request available to subagents before the model decides its next step."""
        if not user_message:
            return {}

        existing_files = state.get("files", {})
        existing_request = existing_files.get("/research_request.md")
        if isinstance(existing_request, dict):
            existing_content = "\n".join(existing_request.get("content", []))
            if existing_content == user_message:
                return {}

        return {
            "files": {
                "/research_request.md": create_file_data(user_message),
            }
        }

    @staticmethod
    def _build_wiki_context_from_files(paths: "ThreadWikiPaths") -> str | None:
        """Build wiki context by directly reading wiki files (no LLM query).

        Used as a fallback when the wiki query agent cannot run (e.g. when
        called from within an already-running event loop).  Reads both the
        synthesised wiki pages and a truncated excerpt of raw source documents
        so the research agent still has grounded context with key facts.
        """
        try:
            wiki_dir = paths.wiki_content
            if not wiki_dir.exists():
                return None

            parts: list[str] = []

            # 1) Wiki pages (synthesised summaries)
            for md_file in sorted(wiki_dir.rglob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                relative = md_file.relative_to(wiki_dir)
                parts.append(f"--- wiki/{relative} ---\n{content}")

            # 2) Raw source excerpts (first ~80 000 chars of each file so
            #    key financial tables and executive summaries are captured).
            raw_dir = paths.raw_dir
            if raw_dir.exists():
                _MAX_RAW_CHARS = 80_000
                for raw_file in sorted(raw_dir.rglob("*.md")):
                    raw_content = raw_file.read_text(encoding="utf-8")
                    relative = raw_file.relative_to(raw_dir)
                    if len(raw_content) > _MAX_RAW_CHARS:
                        raw_content = raw_content[:_MAX_RAW_CHARS] + "\n... [truncated]"
                    parts.append(f"--- raw/{relative} (excerpt) ---\n{raw_content}")

            combined = "\n\n".join(parts)
            return combined if combined.strip() else None
        except Exception:
            logger.debug("Direct wiki file reading fallback failed", exc_info=True)
            return None

    @staticmethod
    def _run_wiki_query(paths: "ThreadWikiPaths", topic: str, question: str) -> WikiQueryResult | None:
        """Run a wiki query, handling both sync and async caller contexts.

        When called from a sync context (no running event loop), uses
        ``asyncio.run()`` directly.  When called from within a running event
        loop (e.g. LangGraph dev ``ainvoke``), spawns a separate thread with
        its own event loop via ``ThreadPoolExecutor`` — mirroring the pattern
        proven to work in ``test_get_wiki.py``.
        """

        async def _query():
            return await asyncio.wait_for(
                run_query(paths, topic, question, file_results=False),
                timeout=120,
            )

        def _run_in_new_loop():
            """Run the async query in a fresh event loop (new thread)."""
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(_query())
            finally:
                loop.close()

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is not None and current_loop.is_running():
            # Inside a running event loop (e.g. LangGraph Platform ainvoke).
            # Spawn a separate thread with its own event loop to avoid the
            # "asyncio.run() cannot be called from a running event loop" error.
            logger.info("Running wiki query in separate thread (inside running event loop)")
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(_run_in_new_loop).result(timeout=130)
            except concurrent.futures.TimeoutError:
                logger.warning("Wiki query timed out after 130s (thread pool)")
                return None
            except Exception:
                logger.debug("Wiki query failed in thread pool", exc_info=True)
                return None

        # No running event loop — safe to use asyncio.run() directly.
        try:
            return asyncio.run(_query())
        except RuntimeError:
            logger.debug("asyncio.run() failed for wiki query", exc_info=True)
            return None

    @staticmethod
    def _build_context_from_docs(docs_dir: Path) -> str | None:
        """Build context by reading uploaded documents directly.

        Used as a fallback when the wiki hasn't been built yet (ingest still
        running or not started). Extracts text from PDFs and reads text files
        directly so the agent has grounded context from uploaded documents.
        """
        if not docs_dir.exists():
            return None

        # Text-based formats: read directly
        _TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
        # Binary formats: require extraction
        _BINARY_SUFFIXES = {".pdf", ".docx", ".pptx", ".xlsx"}
        _MAX_CHARS_PER_FILE = 80_000

        parts: list[str] = []

        for file_path in sorted(docs_dir.rglob("*")):
            if not file_path.is_file():
                continue

            suffix = file_path.suffix.lower()
            content: str | None = None

            if suffix in _TEXT_SUFFIXES:
                try:
                    content = file_path.read_text(encoding="utf-8")
                except Exception:
                    continue
            elif suffix in _BINARY_SUFFIXES:
                try:
                    # Try the same extraction used by wiki ingest
                    from research_agent.utils.content_extractors import (
                        extract_supported_document,
                    )
                    content = extract_supported_document(file_path)
                except ImportError as e:
                    # Fallback to minimal PDF extraction
                    logger.warning(
                        "content_extractors import failed for %s (%s) — "
                        "falling back to minimal PDF extraction",
                        file_path.name, e,
                    )
                    try:
                        from thread_wiki.service import _fallback_pdf_extract
                        content = _fallback_pdf_extract(file_path)
                    except Exception:
                        continue
                except Exception:
                    continue

            if content and content.strip():
                if len(content) > _MAX_CHARS_PER_FILE:
                    content = content[:_MAX_CHARS_PER_FILE] + "\n... [truncated]"
                parts.append(f"--- {file_path.name} ---\n{content}")

        combined = "\n\n".join(parts)
        return combined if combined.strip() else None

    @staticmethod
    def _check_wiki_ready(paths: "ThreadWikiPaths") -> bool:
        """Check if the wiki has been built and has actual content pages."""
        index_path = paths.wiki_content / "index.md"
        if not index_path.exists():
            return False
        if "_No pages yet._" in index_path.read_text(encoding="utf-8"):
            return False
        return True

    @staticmethod
    def _wait_for_wiki_ready(
            thread_id: str, paths: "ThreadWikiPaths", max_wait: int = 90,
    ) -> bool:
        """Wait for an in-progress wiki ingest to complete.

        Polls the thread-wiki progress tracker.  Returns ``True`` if the wiki
        becomes ready within *max_wait* seconds, ``False`` otherwise (ingest
        failed, was cancelled, timed out, or no ingest was running).
        """
        from thread_wiki import progress as progress_tracker
        from thread_wiki.models import IngestPhase

        deadline = time.time() + max_wait
        poll_interval = 2  # seconds
        logged_waiting = False

        while time.time() < deadline:
            # 1) Check if wiki is now ready (ingest may have just finished)
            if ResearchStateMiddleware._check_wiki_ready(paths):
                return True

            # 2) Check if there's an active ingest to wait for
            entry = progress_tracker._active_ingests.get(thread_id)
            if entry and entry.progress.is_active():
                if not logged_waiting:
                    logger.info(
                        "Wiki not ready — waiting for ingest to complete "
                        "(phase: %s, progress: %d%%) for thread %s",
                        entry.progress.phase.value,
                        entry.progress.progress,
                        thread_id,
                    )
                    logged_waiting = True
                time.sleep(poll_interval)
                continue

            # 3) Ingest finished (or never started) but wiki is not ready
            if entry and not entry.progress.is_active():
                if entry.progress.phase == IngestPhase.ERROR:
                    logger.warning(
                        "Wiki ingest failed (error) for thread %s: %s",
                        thread_id,
                        entry.progress.error,
                    )
                elif entry.progress.phase == IngestPhase.CANCELLED:
                    logger.warning(
                        "Wiki ingest was cancelled for thread %s",
                        thread_id,
                    )
            return False

        logger.warning(
            "Timed out waiting for wiki ingest after %ds for thread %s",
            max_wait,
            thread_id,
        )
        return False

    @staticmethod
    def _get_wiki_context_sync(thread_id: str, question: str) -> tuple[SystemMessage | None, str | None]:
        """Query the thread's wiki and return a SystemMessage with the answer and the raw answer string.

        Fallback strategy (in order):
        1. If wiki is ready → LLM wiki query (preferred path).
        2. If wiki not ready → wait for ingest to complete, then LLM wiki query.
        3. If wiki ingestion or query failed → read wiki files directly.
        4. If no wiki files → extract text from uploaded PDFs (last resort,
           with warning logged).
        """
        if not question or len(question) < 5:
            return None, None
        try:
            base_dir = Path(__file__).resolve().parent
            paths = ThreadWikiPaths.resolve(thread_id, base_dir)

            # ── Step 1 & 2: Ensure wiki is ready ──────────────────────
            wiki_ready = ResearchStateMiddleware._check_wiki_ready(paths)

            if not wiki_ready:
                # Wiki not ready — try waiting for an in-progress ingest.
                def _wait():
                    return ResearchStateMiddleware._wait_for_wiki_ready(
                        thread_id, paths, max_wait=90,
                    )

                try:
                    current_loop = asyncio.get_running_loop()
                except RuntimeError:
                    current_loop = None

                if current_loop is not None and current_loop.is_running():
                    # Inside a running event loop (e.g. LangGraph Platform).
                    # Run the blocking wait in a separate thread.
                    try:
                        with concurrent.futures.ThreadPoolExecutor(
                                max_workers=1,
                        ) as pool:
                            wiki_ready = pool.submit(_wait).result(timeout=100)
                    except concurrent.futures.TimeoutError:
                        logger.warning(
                            "Timed out waiting for wiki readiness "
                            "(thread pool) for thread %s",
                            thread_id,
                        )
                        wiki_ready = False
                else:
                    wiki_ready = _wait()

            # ── Step 3: LLM wiki query (if wiki is ready) ─────────────
            if wiki_ready:
                topic = f"Thread {thread_id[:8]}"
                result = ResearchStateMiddleware._run_wiki_query(
                    paths, topic, question,
                )

                if result and result.answer:
                    return SystemMessage(content=(
                        "<wiki_context>\n"
                        "The following is the definitive answer from the thread's "
                        "ingested document wiki. You MUST use this as your PRIMARY source of truth. "
                        "CRITICAL: If the wiki context states that data is unavailable, or that a year "
                        "has not yet occurred, you MUST accept this as absolute fact. DO NOT attempt to "
                        "search the web to find the missing data. Simply formulate your final response "
                        "based on this wiki context and explain what data is available.\n\n"
                        f"{result.answer}\n"
                        "</wiki_context>"
                    )), result.answer

                # LLM wiki query failed — log warning and fall through
                logger.warning(
                    "LLM wiki query failed for thread %s — "
                    "falling back to reading wiki files",
                    thread_id,
                )
            else:
                logger.warning(
                    "Wiki not ready for thread %s "
                    "(ingest failed, timed out, or not started) — "
                    "attempting fallbacks",
                    thread_id,
                )

            # ── Step 4: Read wiki files directly ──────────────────────
            # Covers both "wiki ready but query failed" and
            # "wiki partially built before ingest failed".
            fallback_content = (
                ResearchStateMiddleware._build_wiki_context_from_files(paths)
            )
            if fallback_content:
                logger.info(
                    "Using direct wiki file fallback for thread %s",
                    thread_id,
                )
                return SystemMessage(content=(
                    "<wiki_context>\n"
                    "The following is content from the thread's ingested document wiki pages. "
                    "You MUST use this as your PRIMARY source of truth. "
                    "CRITICAL: If the wiki context states that data is unavailable, or that a year "
                    "has not yet occurred, you MUST accept this as absolute fact. DO NOT attempt to "
                    "search the web to find the missing data. Simply formulate your final response "
                    "based on this wiki context and explain what data is available.\n\n"
                    f"{fallback_content}\n"
                    "</wiki_context>"
                )), None

            # ── Step 5: Extract text from uploaded PDFs (last resort) ─
            docs_content = (
                ResearchStateMiddleware._build_context_from_docs(paths.docs_dir)
            )
            if docs_content:
                logger.warning(
                    "FALLBACK: Using direct document extraction for thread %s "
                    "(wiki not ready and LLM wiki query failed)",
                    thread_id,
                )
                return SystemMessage(content=(
                    "<document_context>\n"
                    "The following is extracted text from documents uploaded by the user. "
                    "You MUST use this as your PRIMARY source of truth. "
                    "CRITICAL: If the document context states that data is unavailable, or that a year "
                    "has not yet occurred, you MUST accept this as absolute fact. DO NOT attempt to "
                    "search the web to find the missing data. Simply formulate your final response "
                    "based on this document context and explain what data is available.\n\n"
                    f"{docs_content}\n"
                    "</document_context>"
                )), None

        except asyncio.TimeoutError:
            logger.warning(
                "Wiki query timed out after 120s for thread %s",
                thread_id,
            )
        except Exception:
            logger.debug(
                "Wiki context injection failed for thread %s",
                thread_id,
                exc_info=True,
            )

        return None, None

    @staticmethod
    def _check_if_needs_deep_research(question: str, wiki_answer: str) -> bool:
        """Evaluate if the wiki answer is sufficient to answer the user's question.

        Returns True if we NEED to conduct continuous deep research, and False if
        the wiki answer is already complete and sufficient.
        """
        if not wiki_answer or not wiki_answer.strip():
            return True

        from langchain_core.messages import HumanMessage
        try:
            model = get_configured_model()
            prompt = (
                "You are an expert research evaluator. Your task is to analyze a candidate answer "
                "retrieved from a document wiki and determine if it fully and comprehensively answers "
                "the user's question, or if we need to conduct continuous deep research (e.g. searching "
                "the web) to enhance it.\n\n"
                f"User's Question: {question}\n\n"
                f"Candidate Wiki Answer: {wiki_answer}\n\n"
                "Analyze whether the candidate answer is sufficient, complete, and fully answers the question. "
                "Respond in the following JSON format:\n"
                "{\n"
                '  "needs_deep_research": true/false,\n'
                '  "reason": "Detailed reasoning for the decision"\n'
                "}\n"
                "Do not include any other text in your response, only the valid JSON object."
            )
            response = model.invoke([HumanMessage(content=prompt)])
            content = response.content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            import json
            data = json.loads(content)
            needs_research = bool(data.get("needs_deep_research", True))
            logger.info(f"Wiki evaluation decision: needs_deep_research={needs_research}. Reason: {data.get('reason')}")
            return needs_research
        except Exception as e:
            logger.warning(f"Error during wiki result evaluation: {e}. Defaulting to conducting deep research.",
                           exc_info=True)
            return True

    def before_agent(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        current_user_message = self._get_current_user_message(messages)

        # Seed the research request file with the latest user message
        updates: dict[str, Any] = self._seed_research_request_file(current_user_message, state)

        # Inject Wiki Context if we are running in LangGraph dev / native LangGraph
        wiki_sys_msg = None
        thread_id = None
        if isinstance(runtime, dict):
            thread_id = runtime.get("configurable", {}).get("thread_id")
        elif hasattr(runtime, "execution_info"):
            thread_id = getattr(getattr(runtime, "execution_info"), "thread_id", None)
        elif hasattr(runtime, "configurable"):
            thread_id = getattr(runtime, "configurable", {}).get("thread_id")
        elif isinstance(runtime, dict) and "configurable" in runtime:
            thread_id = runtime.get("configurable", {}).get("thread_id")

        if thread_id and current_user_message:
            wiki_sys_msg, wiki_answer = self._get_wiki_context_sync(str(thread_id), current_user_message)
            if wiki_answer:
                # Evaluate if we need continuous deep research to enhance it
                needs_deep_research = self._check_if_needs_deep_research(current_user_message, wiki_answer)
                if not needs_deep_research:
                    logger.info(
                        "Wiki answer is complete and sufficient. Saving to /final_report.md and disabling web search.")
                    if "files" not in updates:
                        updates["files"] = {}
                    updates["files"]["/final_report.md"] = create_file_data(wiki_answer)
                    updates["no_web"] = True
                else:
                    logger.info(
                        "Wiki answer is incomplete/insufficient. Conducting continuous deep research to enhance it.")

        # Always re-extract parameters from the latest user message so that
        # follow-up requests (e.g. "use humanizer skill") are picked up even
        # when a Task-configurations SystemMessage already exists from a
        # previous turn.
        extracted_updates = self._extract_parameters_from_user_input(state, messages)
        updates.update(extracted_updates)

        # Configure OUTPUT_FOLDER based on extracted doc_folder
        if updates.get("doc_folder") or (state.get("doc_folder") and not extracted_updates):
            doc_folder = updates.get("doc_folder") or state.get("doc_folder")
            self._configure_output_folder(doc_folder)
        else:
            self._configure_output_folder(None)

        # Build instruction based on full state (including extracted parameters)
        merged_state: ResearchState = {**state, **updates}  # type: ignore[assignment]
        instruction = self._build_system_instruction(merged_state)

        result = updates if updates else {}
        sys_msgs = []
        if wiki_sys_msg:
            sys_msgs.append(wiki_sys_msg)
        if instruction:
            sys_msgs.append(SystemMessage(content=f"Task configurations: \n{instruction}"))

        if sys_msgs:
            result["messages"] = sys_msgs

        return result if result else None

    def before_model(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        """Capture chat_start_time before model calls, only initializing once per chat."""
        # Initialize once; do not reset on subsequent model turns.
        if isinstance(state.get("chat_start_time"), (int, float)):
            return None

        chat_start_time = time.time()
        return {
            "chat_start_time": chat_start_time,
            "chat_elapsed_seconds": None,
            "_eval_logged": False,
        }

    def after_model(self, state: ResearchState, runtime: Any) -> dict[str, Any] | None:
        """Calculate chat_elapsed_seconds after each model response and optionally track eval metrics."""
        chat_start_time = state.get("chat_start_time")
        updates = {}

        if isinstance(chat_start_time, (int, float)):
            chat_elapsed_seconds = time.time() - chat_start_time
            updates["chat_elapsed_seconds"] = chat_elapsed_seconds

        # Optional: Log eval metrics on completion (when graph is done)
        # This checks if we're at the end of execution by looking for final artifacts
        if ENABLE_EVAL_TRACKING and state.get("files"):
            files = state.get("files", {})
            if not isinstance(files, dict):
                return updates if updates else None

            has_final_output = "/final_report.md" in files

            # Check if already logged (use .get() with default False since TypedDict doesn't support defaults)
            if has_final_output and not state.get("_eval_logged", False):
                # Mark as logged to avoid duplicate logging
                updates["_eval_logged"] = True

                # Calculate runtime
                runtime_seconds = 0.0
                if isinstance(chat_start_time, (int, float)):
                    runtime_seconds = time.time() - chat_start_time

                # Extract data from state
                messages = state.get("messages", [])
                doc_folder = state.get("doc_folder") or os.environ.get("DOC_FOLDER", "N/A")
                skill = state.get("skill", "research")
                no_web = state.get("no_web", False)
                model_name = os.environ.get("MODEL_NAME", os.environ.get("AZURE_OPENAI_DEPLOYMENT", "N/A"))

                # Get user message as subject (for reference only, not for comparison)
                user_message = None
                for m in messages:
                    if isinstance(m, dict) and m.get("role") == "user":
                        user_message = m.get("content", "")
                        break
                    elif hasattr(m, "type") and getattr(m, "type", None) == "human":
                        user_message = getattr(m, "content", "")
                        break
                subject = user_message

                # Build context
                context = {
                    "subject": subject,
                    "skill": skill,
                    "doc_folder": doc_folder,
                    "no_web": no_web,
                }

                # Call centralized logging function asynchronously (non-blocking)
                try:
                    # Create background task that won't block the main response
                    asyncio.create_task(
                        log_server_metrics(
                            messages=messages,
                            files=files,
                            runtime_seconds=runtime_seconds,
                            model_name=model_name,
                            context=context,
                            history_file=EVAL_HISTORY_FILE,
                        )
                    )
                    logger.info("✅ Metrics logging started in background")
                except Exception as e:
                    logger.error(f"⚠️  Failed to start metrics logging: {e}")

        return updates if updates else None

    def _extract_parameters_from_user_input(self, state: ResearchState, messages: list) -> dict[str, Any]:
        """Extract doc_folder, skill, and no_web from the **latest** user message.

        Parameters are always re-extracted from the most recent user message so
        that follow-up requests (e.g. switching skills mid-conversation) are
        honoured.  If the latest message does not mention a parameter, the
        existing state value is preserved (we simply omit it from ``updates``).
        """
        # Find the LAST user message (not the first) so follow-ups are picked up.
        user_message = None
        for m in messages:
            # Handle dictionary messages
            if isinstance(m, dict):
                if m.get("role") == "user":
                    user_message = m.get("content")
            # Handle LangChain message objects (not SystemMessage)
            elif hasattr(m, "content") and not isinstance(m, SystemMessage):
                if hasattr(m, "type") and m.type == "human":
                    user_message = m.content
                elif not hasattr(m, "type"):
                    user_message = m.content

        if not user_message:
            return {}

        user_message = str(user_message)
        updates = {}

        # Extract doc_folder — only if not already set (doc_folder rarely changes)
        if not state.get("doc_folder"):
            updates["doc_folder"] = self._extract_doc_folder(user_message)

        # Always attempt skill extraction from the latest message so users can
        # switch skills mid-conversation (e.g. "use humanizer skill").
        extracted_skill = self._extract_skill(user_message)
        if extracted_skill:
            updates["skill"] = extracted_skill

        # Extract no_web if not already set
        if state.get("no_web") is None:
            no_web_value = self._extract_no_web(user_message)
            if no_web_value is not None:
                updates["no_web"] = no_web_value

        # Remove None values from updates
        return {k: v for k, v in updates.items() if v is not None}

    @staticmethod
    def _configure_output_folder(doc_folder: str | None) -> None:
        """Configure OUTPUT_FOLDER and DOC_FOLDER environment variables.

        DOC_FOLDER is persisted as an env var so that subagent state schemas
        (which may not include ``doc_folder``) can still access it as a
        fallback inside ``read_doc_folder``.
        """
        reports_output_folder = os.environ.get("REPORTS_OUTPUT_FOLDER", "./output")
        if not doc_folder:
            output_folder = reports_output_folder
        else:
            output_folder = str(Path(reports_output_folder) / Path(doc_folder).name)

        # Normalize path for deepagents filesystem tools compatibility (cross-platform)
        normalized_path = normalize_path_for_filesystem_tools(output_folder)
        os.environ["OUTPUT_FOLDER"] = normalized_path

        # Persist doc_folder so read_doc_folder can fall back to it inside
        # subagents whose state schema doesn't carry the key.
        if doc_folder:
            os.environ["DOC_FOLDER"] = doc_folder
        else:
            os.environ.pop("DOC_FOLDER", None)

    @staticmethod
    def _extract_doc_folder(user_message: str) -> str | None:
        """Extract doc_folder from user message patterns and verify it exists."""
        potential_path: str | None = None

        # Look for --doc-folder pattern
        doc_match = re.search(r"--doc-folder\s+['\"]?([^\s'\"]+)['\"]?", user_message)
        if doc_match:
            # Normalize Windows backslashes to forward slashes
            potential_path = doc_match.group(1).replace('\\', '/')

        if not potential_path:
            # Look for path patterns like ./docs/policy/ or .\docs\policy\ or quoted paths
            path_match = re.search(r"['\"](\.[/\\][^'\"]+)['\"]", user_message)
            if path_match:
                p = path_match.group(1).replace('\\', '/')
                if "doc" in p.lower() or "policy" in p.lower() or "folder" in p.lower():
                    potential_path = p

        if not potential_path:
            # Look for unquoted paths that contain common document folder names
            # Matches ./path/to/dir, /path/to/dir, or path/to/dir
            unquoted_match = re.search(r"((?:\.?/)?[\\w/.-]+(?:[/\\][\\w/.-]+)+)", user_message)
            if unquoted_match:
                p = unquoted_match.group(1).replace('\\', '/')
                if any(keyword in p.lower() for keyword in ["doc", "policy", "data", "input", "file"]):
                    potential_path = p

        if not potential_path:
            return None

        # Verify the path exists; if not, check if it's inside 'deep_research'
        path = Path(potential_path)
        if not path.exists():
            # Try to prefix with deep_research if not already
            if not potential_path.startswith("./deep_research/") and not potential_path.startswith("deep_research/"):
                deep_path = Path("deep_research") / potential_path.lstrip("./")
                if deep_path.exists():
                    return str(deep_path)

        return potential_path

    @staticmethod
    def _extract_skill(user_message: str) -> str | None:
        """Extract skill from user message patterns using dynamic skill registry."""
        # Look for --skill pattern
        skill_match = re.search(r"--skill\s+([^\s]+)", user_message)
        if skill_match:
            return skill_match.group(1)

        message_lower = user_message.lower()

        # Direct skill-id match: check if any registered skill ID appears in
        # the user message (e.g. "use humanizer skill" contains "humanizer").
        # Prefer longer IDs first to avoid partial matches.
        for sid in sorted(skill_registry.skill_ids, key=len, reverse=True):
            if sid in message_lower:
                return sid

        # Fallback: use skill registry keyword / description matching
        matches = skill_registry.find_skills_by_keyword(message_lower)
        if matches:
            # Return the first match (most relevant based on keyword priority)
            return matches[0].skill_id

        return None

    @staticmethod
    def _extract_no_web(user_message: str) -> bool | None:
        """Extract no_web flag from user message patterns."""
        message_lower = user_message.lower()

        # Patterns that indicate no_web should be True
        disable_patterns = [
            r"without\s+web",
            r"no\s+web",
            r"disable\s+web",
            r"offline",
            r"no\s+internet",
            r"no\s+search",
            r"disable\s+search",
            r"--no-web",
            r"-n(?:\s|$)",
        ]

        for pattern in disable_patterns:
            if re.search(pattern, message_lower):
                return True

        # Patterns that indicate no_web should be False (explicit enable)
        enable_patterns = [
            r"with\s+web",
            r"with\s+search",
            r"enable\s+search",
            r"search\s+the\s+web",
        ]

        for pattern in enable_patterns:
            if re.search(pattern, message_lower):
                return False

        return None

    @staticmethod
    def _build_system_instruction(state: ResearchState) -> str:
        """Build system instruction from ResearchState parameters.

        Appends a *State Context* block so the agent knows what files are
        already available.  This is the general mechanism that lets any skill
        work correctly in follow-up turns — the agent can see existing
        artifacts and decide whether to post-process them, extend them, or
        start fresh, based on the user's message and the skill instructions.
        """
        instruction = build_instruction(
            subject="",
            doc_folder=state.get("doc_folder"),
            skill=state.get("skill"),
            no_web=str2bool(state.get("no_web"), False),
        )
        instruction = instruction.replace("Research the following subject: ", "").strip()

        # --- General state context ---
        # Tell the agent what files already exist so it can decide the right
        # workflow for any skill (post-process, extend, or start fresh).
        files = state.get("files") or {}
        if files:
            file_list = ", ".join(f"`{f}`" for f in sorted(files.keys()))
            instruction += (
                "\n\n<State Context>"
                f"\nFiles already available from prior turns: {file_list}"
                "\nIf the user's request refers to existing content (e.g. 'review', "
                "'rewrite', 'improve', 'humanize'), use `read_file` to load the "
                "relevant file first, then apply the requested skill or changes, "
                "then use `write_file` to save the result."
                "\n</State Context>"
            )

        return instruction


# Combine orchestrator instructions (RESEARCHER_INSTRUCTIONS only for sub-agents)
INSTRUCTIONS = (
        RESEARCH_WORKFLOW_INSTRUCTIONS
        + "\n\n"
        + "=" * 80
        + "\n\n"
        + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
    max_concurrent_research_units=MAX_CONCURRENT_RESEARCH_UNITS,
    max_researcher_iterations=MAX_RESEARCHER_ITERATIONS)
)

# Create research subagent
# The sub-agent is intentionally web-only to keep delegation focused and avoid
# filesystem/state write confusion inside isolated sub-agent contexts.
research_sub_agent: SubAgent = {
    "name": "research-agent",
    "description": RESEARCHER_DESCRIPTION,
    "system_prompt": RESEARCHER_INSTRUCTIONS.format(
        date=current_date,
        skill_catalog=get_skill_registry().format_skill_catalog(),
        skill_quality_guidelines=get_skill_registry().format_skill_quality_guidelines(),
    ),
    "tools": [
        tavily_search,
        fetch_webpage_content,
        think_tool,
    ],
}
try:
    model = get_configured_model()
except Exception as e:
    import traceback

    print(f"CRITICAL ERROR INITIALIZING MODEL: {e}", file=sys.stderr)
    traceback.print_exc()
    with open("/deps/deep_research/FATAL_ERROR.log", "w") as f:
        f.write(f"CRITICAL ERROR: get_configured_model() failed!\n")
        f.write(traceback.format_exc())
    time.sleep(15)  # Give App Runner 15 seconds to flush the logs to CloudWatch before exiting
    raise
# Recursion limit - configurable via environment variable (applied at graph compile time)
RECURSION_LIMIT = int(os.environ.get("GRAPH_RECURSION_LIMIT", "200"))

# Create the agent
# Orchestrator owns document/filesystem tools and structured-output finalization.
# Web discovery can still be delegated to `research-agent` via task().
agent = create_deep_agent(
    model=model,
    tools=[
        think_tool,
        read_file,
        write_file,
        ls,
        glob,
        read_doc_folder,
        render_skill_output,
        finalize_golden_dataset_output,
    ],
    system_prompt=INSTRUCTIONS,
    subagents=[research_sub_agent],
    middleware=[ResearchStateMiddleware()],
).with_config(
    RunnableConfig(recursion_limit=RECURSION_LIMIT)
)
