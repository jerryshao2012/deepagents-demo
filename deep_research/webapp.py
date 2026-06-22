import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

DOCS_ROOT = Path(__file__).resolve().parent / "docs"

# API version - increment this with each new build
API_VERSION = "1.8.59"

# API Key for authentication (from environment variable)
API_KEY = os.environ.get("UPLOAD_API_KEY") or os.environ.get("LANGCHAIN_API_KEY", "")
if not API_KEY:
    # Generate a default key for development (should be set in production)
    import secrets

    API_KEY = secrets.token_urlsafe(32)
    print(f"⚠️  WARNING: UPLOAD_API_KEY not set. Using generated key: {API_KEY}")
    print("   Set UPLOAD_API_KEY in your .env file for production use.")

# Import OAuth handlers
try:
    from oauth_handler import (
        get_oauth_login_url,
        handle_github_callback,
        handle_google_callback,
        handle_logout,
        user_manager,
    )

    OAUTH_ENABLED = True
except ImportError:
    OAUTH_ENABLED = False
    print("⚠️  OAuth dependencies not installed. OAuth login will be disabled.")


def _is_authenticated(x_api_key: str | None, request: Request = None) -> bool:
    # 1. Check static API Key
    if x_api_key and x_api_key == API_KEY:
        return True

    # 2. Check OAuth session token if enabled
    if OAUTH_ENABLED:
        token = x_api_key
        if not token and request:
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
        if token and user_manager.validate_session(token):
            return True

    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    # Try to import db and init it if it exists (for server.py use case)
    try:
        import db
        db.init_db()
        print("✅ Database initialized via lifespan")
    except (ImportError, AttributeError):
        pass

    yield
    # Shutdown logic (if any)


app = FastAPI(
    title="Document Upload API",
    description="Upload documents to the deep research agent docs folder",
    version=API_VERSION,
    lifespan=lifespan
)

frontend_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://smith.langchain.com",
]

# Support one or more explicit frontend origins from env.
# Accept comma-separated values and normalize by trimming trailing slashes.
env_frontend_urls = os.environ.get("FRONTEND_URL", "")
if env_frontend_urls:
    frontend_origins.extend(
        origin.strip().rstrip("/")
        for origin in env_frontend_urls.split(",")
        if origin.strip()
    )

# Deduplicate while preserving order and remove any accidental empties.
frontend_origins = list(dict.fromkeys(origin for origin in frontend_origins if origin))

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    # Allow local development UI hosts on any port.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.sessions import SessionMiddleware

app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("OAUTH_SECRET_KEY", "oauth-session-secret-key-fallback-for-dev"),
)

# Register thread wiki routes
from thread_wiki.routes import router as wiki_router

app.include_router(wiki_router)


def _safe_relative_folder(folder: str) -> PurePosixPath:
    """Return a safe relative folder path inside docs."""
    normalized = folder.replace("\\", "/").strip().strip("/")
    path = PurePosixPath(normalized)
    if (
            not normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="folder must be a relative path inside docs",
        )
    return path


def _safe_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded files must include filenames",
        )

    name = PurePosixPath(filename.replace("\\", "/")).name
    if not name or name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="uploaded files must include valid filenames",
        )
    return name


@app.post("/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_documents(
        request: Request,
        folder: str = Form("policy"),
        files: list[UploadFile] = File(...),
        x_api_key: str | None = Header(None),
) -> dict:
    """Upload documents to a specified folder within docs directory.

    Requires API key authentication via X-API-Key header.
    Returns uploaded file info and remaining free storage space.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    relative_folder = _safe_relative_folder(folder)
    destination_dir = DOCS_ROOT.joinpath(*relative_folder.parts)
    await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)

    saved = []
    total_uploaded_size = 0
    for upload in files:
        filename = _safe_filename(upload.filename)
        content = await upload.read()
        destination = destination_dir / filename
        await asyncio.to_thread(destination.write_bytes, content)
        file_size = len(content)
        total_uploaded_size += file_size
        saved.append(
            {
                "filename": filename,
                "path": str(PurePosixPath("docs", *relative_folder.parts, filename)),
                "size": file_size,
            }
        )

    # Calculate free storage space
    free_space = await asyncio.to_thread(_get_free_space, DOCS_ROOT.parent)

    # Auto-trigger wiki ingest if uploading to a thread folder
    thread_id = _extract_thread_id_from_folder(str(relative_folder))
    if thread_id:
        asyncio.create_task(
            _trigger_wiki_auto_ingest(thread_id),
            name=f"wiki-auto-ingest-trigger-{thread_id}",
        )

    return {
        "folder": str(relative_folder),
        "count": len(saved),
        "saved": saved,
        "total_uploaded_bytes": total_uploaded_size,
        "free_space_bytes": free_space,
        "free_space_human": _format_bytes(free_space),
    }


def _format_bytes(bytes_value: int) -> str:
    """Format bytes into human-readable format."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def _get_free_space(path: Path) -> int:
    """Get free disk space in bytes for the given path."""
    try:
        stat = shutil.disk_usage(str(path))
        return stat.free
    except Exception:
        # Fallback: return -1 if unable to determine
        return -1


# ── Thread Wiki auto-ingest hooks ────────────────────────────────────────────

def _extract_thread_id_from_folder(folder_str: str) -> str | None:
    """Extract thread_id if the folder matches 'threads/<thread-id>' pattern."""
    parts = PurePosixPath(folder_str.replace("\\", "/").strip("/")).parts
    if len(parts) == 2 and parts[0] == "threads":
        return parts[1]
    return None


async def _trigger_wiki_auto_ingest(thread_id: str) -> None:
    """Trigger background wiki ingest for a thread after document upload.

    Runs non-blocking; failures are logged but do not affect the upload response.
    """
    try:
        from thread_wiki import progress as wiki_progress
        from thread_wiki.models import ThreadWikiPaths
        from thread_wiki.service import run_ingest

        base_dir = Path(__file__).resolve().parent
        paths = ThreadWikiPaths.resolve(thread_id, base_dir)
        topic = f"Thread {thread_id[:8]}"

        # Register progress first with a placeholder task.
        placeholder = asyncio.create_task(asyncio.sleep(0))
        prog = await wiki_progress.register_ingest(thread_id, placeholder)
        cancel_event = wiki_progress._active_ingests[thread_id].cancel_event

        # Create the real background task.
        task = asyncio.create_task(
            _wiki_ingest_background(paths, topic, prog, cancel_event),
            name=f"wiki-auto-ingest-{thread_id}",
        )

        # Replace placeholder with the real task.
        wiki_progress._active_ingests[thread_id] = wiki_progress._IngestEntry(
            progress=prog, task=task, cancel_event=cancel_event,
        )
        prog.advance(prog.phase, "Auto-ingest queued after upload.")
        logger.info("Auto-ingest triggered for thread %s", thread_id)
    except Exception:
        logger.exception("Failed to trigger wiki auto-ingest for thread %s", thread_id)


async def _wiki_ingest_background(paths, topic: str, progress_obj, cancel_event) -> None:
    """Background wrapper for auto-ingest."""
    from thread_wiki import progress as wiki_progress
    from thread_wiki.service import run_ingest

    try:
        await run_ingest(paths, topic, progress_obj, cancel_event)
    except asyncio.CancelledError:
        logger.info("Auto-ingest cancelled for thread %s", paths.thread_id)
    except Exception:
        logger.exception("Auto-ingest failed for thread %s", paths.thread_id)
    finally:
        await wiki_progress.cleanup_terminal(paths.thread_id)


async def _trigger_wiki_delete_hooks(thread_id: str, deleted_filename: str | None = None) -> None:
    """Cancel any active ingest and trigger lint after document deletion.

    Steps:
    1. Cancel any running ingest for this thread (to prevent stale writes).
    2. Trigger a background lint reconciliation to clean up wiki references.
    """
    try:
        from thread_wiki import progress as wiki_progress
        from thread_wiki.models import ThreadWikiPaths
        from thread_wiki.service import run_lint

        # Step 1: Cancel active ingest.
        cancelled = await wiki_progress.cancel_ingest(
            thread_id, reason=f"Document deleted: {deleted_filename or 'multiple'}"
        )
        if cancelled:
            logger.info("Cancelled active ingest for thread %s due to deletion", thread_id)

        # Step 2: Trigger lint reconciliation in background.
        base_dir = Path(__file__).resolve().parent
        paths = ThreadWikiPaths.resolve(thread_id, base_dir)
        if paths.wiki_dir.exists():
            topic = f"Thread {thread_id[:8]}"
            note = (
                f"Source file '{deleted_filename}' was deleted. "
                "Reconcile wiki pages that reference it."
                if deleted_filename
                else "Multiple source files were deleted. Reconcile wiki pages."
            )
            asyncio.create_task(
                _wiki_lint_background(paths, topic, note),
                name=f"wiki-lint-{thread_id}",
            )
            logger.info("Lint triggered for thread %s after deletion", thread_id)
    except Exception:
        logger.exception("Failed to trigger wiki delete hooks for thread %s", thread_id)


async def _wiki_lint_background(paths, topic: str, note: str) -> None:
    """Background wrapper for lint after deletion."""
    from thread_wiki.service import run_lint
    try:
        await run_lint(paths, topic, note=note)
    except Exception:
        logger.exception("Lint failed for thread %s", paths.thread_id)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    free_space = await asyncio.to_thread(_get_free_space, DOCS_ROOT.parent)
    return {
        "status": "healthy",
        "version": API_VERSION,
        "docs_root": str(DOCS_ROOT),
        "free_space_bytes": free_space,
        "free_space_human": _format_bytes(free_space),
    }


@app.get("/storage/info")
async def storage_info(request: Request, x_api_key: str | None = Header(None)):
    """Get server storage details and model factory diagnostics.

    Requires API key authentication via X-API-Key header.
    Returns storage info, detected model provider configuration, and a
    quick connectivity test (single short prompt) for fast diagnosis.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    total, used, free = await asyncio.to_thread(shutil.disk_usage, str(DOCS_ROOT.parent))

    # --- Model factory diagnostics ---
    model_diagnostics = await _run_model_diagnostics()

    return {
        "storage": {
            "total_space_bytes": total,
            "used_space_bytes": used,
            "free_space_bytes": free,
            "total_space_human": _format_bytes(total),
            "used_space_human": _format_bytes(used),
            "free_space_human": _format_bytes(free),
            "usage_percentage": round((used / total) * 100, 2) if total > 0 else 0,
        },
        "model_factory": model_diagnostics,
        "environment_variables": dict(os.environ),
    }


async def _run_model_diagnostics() -> dict:
    """Run a quick diagnostic on model_factory: detect provider, show config,
    and send a minimal test prompt to verify end-to-end connectivity."""
    import time

    diagnostics: dict = {
        "detected_provider": None,
        "configuration": {},
        "model_creation": {"success": False, "error": None, "elapsed_seconds": None},
        "test_request": {"success": False, "prompt": None, "response": None, "error": None, "elapsed_seconds": None},
    }

    # --- Detect provider & collect relevant config ---
    provider, config = _detect_model_provider()
    diagnostics["detected_provider"] = provider
    diagnostics["configuration"] = config

    if provider == "none":
        diagnostics["model_creation"]["error"] = "No supported model provider environment variables found."
        return diagnostics

    # --- Try to create the model ---
    t0 = time.monotonic()
    try:
        model = await asyncio.to_thread(_create_model_safe)
        elapsed = round(time.monotonic() - t0, 3)
        diagnostics["model_creation"] = {
            "success": True,
            "error": None,
            "elapsed_seconds": elapsed,
            "model_type": type(model).__name__,
            "model_repr": repr(model)[:500],
        }
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 3)
        diagnostics["model_creation"] = {
            "success": False,
            "error": str(exc),
            "elapsed_seconds": elapsed,
        }
        return diagnostics  # cannot proceed to test request

    # --- Send a minimal test prompt ---
    test_prompt = "Reply with exactly: OK"
    try:
        t0 = time.monotonic()
        response = await asyncio.to_thread(model.invoke, test_prompt)
        elapsed = round(time.monotonic() - t0, 3)
        diagnostics["test_request"] = {
            "success": True,
            "prompt": test_prompt,
            "response": str(response.content)[:500] if hasattr(response, "content") else str(response)[:500],
            "response_metadata": _extract_response_metadata(response),
            "error": None,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        elapsed = round(time.monotonic() - t0, 3)
        diagnostics["test_request"] = {
            "success": False,
            "prompt": test_prompt,
            "response": None,
            "error": str(exc),
            "elapsed_seconds": elapsed,
        }

    return diagnostics


def _detect_model_provider() -> tuple[str, dict]:
    """Detect which model provider is configured based on env vars and
    return the relevant configuration values (secrets masked)."""

    def _mask(value: str | None, visible: int = 4) -> str | None:
        if not value:
            return None
        if len(value) <= visible:
            return "****"
        return value[:visible] + "*" * (len(value) - visible)

    # AWS Bedrock
    if os.getenv("AWS_BEDROCK_ENDPOINT") and os.getenv("AWS_BEARER_TOKEN_BEDROCK") and os.getenv("MODEL_NAME"):
        return "aws_bedrock", {
            "AWS_BEDROCK_ENDPOINT": os.getenv("AWS_BEDROCK_ENDPOINT"),
            "AWS_BEARER_TOKEN_BEDROCK": _mask(os.getenv("AWS_BEARER_TOKEN_BEDROCK")),
            "MODEL_NAME": os.getenv("MODEL_NAME"),
        }

    # Azure OpenAI (legacy with API version)
    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and (os.getenv("AZURE_OPENAI_API_KEY")
                 or (os.getenv("AZURE_CLIENT_ID") and os.getenv("AZURE_OPENAI_SCOPE")))
            and os.getenv("AZURE_OPENAI_API_VERSION")
    ):
        auth_type = os.getenv("AZURE_AUTH_TYPE", "api_key")
        return "azure_openai_legacy", {
            "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
            "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            "AZURE_OPENAI_API_VERSION": os.getenv("AZURE_OPENAI_API_VERSION"),
            "AZURE_AUTH_TYPE": auth_type,
            "AZURE_OPENAI_API_KEY": _mask(os.getenv("AZURE_OPENAI_API_KEY")),
            "AZURE_CLIENT_ID": os.getenv("AZURE_CLIENT_ID"),
            "AZURE_OPENAI_SCOPE": os.getenv("AZURE_OPENAI_SCOPE"),
        }

    # Azure OpenAI (new, without explicit API version)
    if (
            os.getenv("AZURE_OPENAI_ENDPOINT")
            and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            and os.getenv("AZURE_OPENAI_API_KEY")
    ):
        return "azure_openai", {
            "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
            "AZURE_OPENAI_DEPLOYMENT": os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            "AZURE_OPENAI_API_KEY": _mask(os.getenv("AZURE_OPENAI_API_KEY")),
        }

    # Google Gemini
    if os.getenv("GOOGLE_API_KEY") and os.getenv("MODEL_NAME"):
        return "google_gemini", {
            "GOOGLE_API_KEY": _mask(os.getenv("GOOGLE_API_KEY")),
            "MODEL_NAME": os.getenv("MODEL_NAME"),
        }

    # Anthropic
    if os.getenv("ANTHROPIC_API_KEY") and os.getenv("MODEL_NAME"):
        return "anthropic", {
            "ANTHROPIC_API_KEY": _mask(os.getenv("ANTHROPIC_API_KEY")),
            "MODEL_NAME": os.getenv("MODEL_NAME"),
        }

    # Ollama
    if os.getenv("OLLAMA_API_BASE") and os.getenv("MODEL_NAME"):
        return "ollama", {
            "OLLAMA_API_BASE": os.getenv("OLLAMA_API_BASE"),
            "MODEL_NAME": os.getenv("MODEL_NAME"),
        }

    return "none", {}


def _create_model_safe():
    """Import and call model_factory.get_configured_model()."""
    from model_factory import get_configured_model
    return get_configured_model()


def _extract_response_metadata(response) -> dict:
    """Safely extract useful metadata from a LangChain response."""
    meta: dict = {}
    if hasattr(response, "response_metadata") and response.response_metadata:
        # Keep only serializable, non-sensitive fields
        rm = response.response_metadata
        for key in ("model_name", "model_provider", "finish_reason", "usage"):
            if key in rm:
                meta[key] = rm[key]
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        meta["usage_metadata"] = response.usage_metadata
    return meta


@app.get("/documents/list")
async def list_documents(
        request: Request,
        folder: str = "policy",
        x_api_key: str | None = Header(None),
) -> dict:
    """List all files in a specified folder within docs directory.

    Requires API key authentication via X-API-Key header.
    Returns array of files with name and size.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    relative_folder = _safe_relative_folder(folder)
    target_dir = DOCS_ROOT.joinpath(*relative_folder.parts)

    if not target_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Folder '{folder}' does not exist",
        )

    if not target_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{folder}' is not a directory",
        )

    # List all files and folders in the directory (non-recursive)
    items = []

    def _list_items():
        res = []
        for item in target_dir.iterdir():
            if item.is_file():
                res.append({
                    "name": item.name,
                    "type": "file",
                    "size": item.stat().st_size,
                })
            elif item.is_dir():
                res.append({
                    "name": item.name,
                    "type": "folder",
                    "size": None,
                })
        return res

    items = await asyncio.to_thread(_list_items)

    # Sort by name for consistent ordering
    items.sort(key=lambda x: x["name"])

    return {
        "folder": str(relative_folder),
        "count": len(items),
        "items": items,
    }


@app.get("/documents/download/{filename}")
async def download_document(
        request: Request,
        filename: str,
        folder: str = "policy",
        x_api_key: str | None = Header(None),
):
    """Download a specific file from a folder.

    Requires API key authentication via X-API-Key header.
    Returns the file as a downloadable response.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    # Validate filename
    safe_name = _safe_filename(filename)

    relative_folder = _safe_relative_folder(folder)
    file_path = DOCS_ROOT.joinpath(*relative_folder.parts, safe_name)

    def _check_exists():
        return file_path.exists()

    def _check_is_file():
        return file_path.is_file()

    if not (await asyncio.to_thread(_check_exists)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' not found in folder '{folder}'",
        )

    if not (await asyncio.to_thread(_check_is_file)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{filename}' is not a file",
        )

    # Determine media type based on file extension
    media_type = "application/octet-stream"  # Default
    ext = file_path.suffix.lower()

    # Common document types
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in [".doc", ".docx"]:
        media_type = "application/msword"
    elif ext in [".xls", ".xlsx"]:
        media_type = "application/vnd.ms-excel"
    elif ext in [".ppt", ".pptx"]:
        media_type = "application/vnd.ms-powerpoint"
    elif ext == ".txt":
        media_type = "text/plain"
    elif ext in [".md", ".markdown"]:
        media_type = "text/markdown"
    elif ext in [".json"]:
        media_type = "application/json"
    elif ext in [".csv"]:
        media_type = "text/csv"

    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type=media_type,
    )


@app.delete("/documents/{filename}", status_code=status.HTTP_200_OK)
async def delete_document(
        request: Request,
        filename: str,
        folder: str = "policy",
        x_api_key: str | None = Header(None),
) -> dict:
    """Delete a specific file from a folder.

    Requires API key authentication via X-API-Key header.
    Returns confirmation of deletion.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    # Validate filename
    safe_name = _safe_filename(filename)

    relative_folder = _safe_relative_folder(folder)
    file_path = DOCS_ROOT.joinpath(*relative_folder.parts, safe_name)

    def _check_exists():
        return file_path.exists()

    def _check_is_file():
        return file_path.is_file()

    if not (await asyncio.to_thread(_check_exists)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{filename}' not found in folder '{folder}'",
        )

    if not (await asyncio.to_thread(_check_is_file)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{filename}' is not a file",
        )

    # Delete the file
    def _delete_file():
        file_path.unlink()
        return True

    await asyncio.to_thread(_delete_file)

    # Trigger wiki delete hooks (cancel ingest + lint) for thread folders
    thread_id = _extract_thread_id_from_folder(str(relative_folder))
    if thread_id:
        asyncio.create_task(
            _trigger_wiki_delete_hooks(thread_id, deleted_filename=safe_name),
            name=f"wiki-delete-hook-{thread_id}",
        )

    return {
        "message": f"File '{filename}' deleted successfully",
        "folder": str(relative_folder),
        "filename": safe_name,
    }


@app.delete("/documents/folder/{folder}", status_code=status.HTTP_200_OK)
async def delete_folder_contents(
        request: Request,
        folder: str,
        x_api_key: str | None = Header(None),
) -> dict:
    """Delete all files in a specified folder.

    Requires API key authentication via X-API-Key header.
    Returns count of deleted files.
    """
    # Validate API key / session token
    if not _is_authenticated(x_api_key, request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
        )

    relative_folder = _safe_relative_folder(folder)
    target_dir = DOCS_ROOT.joinpath(*relative_folder.parts)

    if not target_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Folder '{folder}' does not exist",
        )

    if not target_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"'{folder}' is not a directory",
        )

    # Delete all files in the directory (non-recursive)
    def _delete_files():
        deleted_count = 0
        for item in target_dir.iterdir():
            if item.is_file():
                item.unlink()
                deleted_count += 1
        return deleted_count

    deleted_count = await asyncio.to_thread(_delete_files)

    # Trigger wiki delete hooks (cancel ingest + lint) for thread folders
    thread_id = _extract_thread_id_from_folder(str(relative_folder))
    if thread_id:
        asyncio.create_task(
            _trigger_wiki_delete_hooks(thread_id),
            name=f"wiki-folder-delete-hook-{thread_id}",
        )

    return {
        "message": f"All files deleted from folder '{folder}'",
        "folder": str(relative_folder),
        "deleted_count": deleted_count,
    }


# OAuth Authentication Endpoints
@app.get("/auth/login/{provider}")
async def oauth_login(provider: str, request: Request):
    """Initiate OAuth login with Google or GitHub.

    Usage:
    - GET /auth/login/google
    - GET /auth/login/github
    """
    if not OAUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled. Install required dependencies.",
        )

    if provider not in ["google", "github"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}. Use 'google' or 'github'.",
        )

    # Get base URL from request, respecting forwarded headers from proxy
    # Azure Container Apps sends X-Forwarded-Proto and X-Forwarded-Host headers
    forwarded_proto = request.headers.get("x-forwarded-proto", "http")
    forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))

    if forwarded_host:
        base_url = f"{forwarded_proto}://{forwarded_host}"
    else:
        base_url = str(request.base_url).rstrip("/")

    redirect_uri = f"{base_url}/auth/callback/{provider}"

    try:
        login_url = await get_oauth_login_url(request, provider, redirect_uri)
        return RedirectResponse(url=login_url)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate login URL: {str(e)}",
        )


@app.get("/auth/callback/{provider}")
async def oauth_callback(provider: str, request: Request):
    """Handle OAuth callback from Google or GitHub.

    Returns user information and session token.
    """
    if not OAUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled.",
        )

    if provider not in ["google", "github"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}.",
        )

    try:
        if provider == "google":
            user_data = await handle_google_callback(request)
        else:
            user_data = await handle_github_callback(request)

        # Redirect back to the frontend with the session token
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
        session_token = user_data["session_token"]
        return RedirectResponse(url=f"{frontend_url}/login/success?token={session_token}")

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth authentication failed: {str(e)}",
        )


@app.get("/auth/session/validate")
async def validate_session(request: Request, x_api_key: str | None = Header(None)):
    """Validate an OAuth session token.

    Provide session token via X-API-Key header or Authorization: Bearer header.
    """
    if not OAUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled.",
        )

    # Get token from header
    token = x_api_key
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token.",
        )

    # Validate session
    user_data = user_manager.validate_session(token)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token.",
        )

    return {
        "valid": True,
        "user": {
            "identity": user_data["identity"],
            "email": user_data.get("email"),
            "name": user_data.get("name"),
            "provider": user_data.get("provider"),
            "avatar_url": user_data.get("picture") or user_data.get("avatar_url"),
        },
        "metadata": {
            k: v
            for k, v in user_data.items()
            if k
               not in [
                   "identity",
                   "email",
                   "name",
                   "provider",
                   "picture",
                   "avatar_url",
                   "raw_token",
                   "session_token",
               ]
        },
    }


@app.post("/auth/logout")
async def logout(request: Request, x_api_key: str | None = Header(None)):
    """Logout user by invalidating their OAuth session token.

    Provide session token via X-API-Key header or Authorization: Bearer header.
    Returns success message and cleaned up user identity.
    """
    if not OAUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth authentication is not enabled.",
        )

    # Get token from header
    token = x_api_key
    if not token:
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token.",
        )

    # Handle logout - this removes the session and returns user identity
    identity = handle_logout(token)
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or already expired.",
        )

    # Clean up the logged users tracking in auth module
    from auth import _logged_oauth_users
    if identity in _logged_oauth_users:
        _logged_oauth_users.discard(identity)
        print(f"✅ Cleaned up logged user tracking for: {identity}")

    return {
        "success": True,
        "message": "Successfully logged out",
        "identity": identity,
    }


if __name__ == "__main__":
    import uvicorn

    # Get host and port from environment or use defaults
    host = os.environ.get("UPLOAD_HOST", "0.0.0.0")  # Listen on all interfaces by default
    port = int(os.environ.get("UPLOAD_PORT", "8000"))

    print(f"🚀 Starting Document Upload API on {host}:{port}")
    print(f"📁 Documents root: {DOCS_ROOT}")
    print(f"🔑 API Key authentication: {'Enabled' if API_KEY else 'Disabled'}")
    print(f"📦 API Version: {API_VERSION}")
    print(f"\n💡 Usage example:")
    print(f"   curl -X POST http://{host}:{port}/documents/upload \\")
    print(f"     -H 'X-API-Key: {API_KEY}' \\")
    print(f"     -F 'folder=policy' \\")
    print(f"     -F 'files=@your_file.pdf'")

    uvicorn.run(app, host=host, port=port)
