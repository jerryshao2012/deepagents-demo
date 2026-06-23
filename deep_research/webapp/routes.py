"""All HTTP route handlers for the webapp.

Routes are registered on module-level functions decorated directly with
``@app.get/post/delete``.  The FastAPI ``app`` instance is imported lazily
(via ``_get_app()``) to avoid circular-import issues with ``webapp/__init__``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import PurePosixPath
from typing import Any

import sys
from fastapi import File, Form, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse

from . import config as _cfg
from .auth_helpers import is_authenticated
from .model_diagnostics import run_model_diagnostics
from .utils import (
    detect_media_type,
    extract_thread_id_from_folder,
    format_bytes,
    get_free_space,
    safe_filename,
    safe_relative_folder,
)
from .wiki_hooks import trigger_wiki_auto_ingest, trigger_wiki_delete_hooks

logger = logging.getLogger(__name__)


def _webapp_module():
    """Return the top-level ``webapp`` package module (for monkeypatched attrs)."""
    return sys.modules["webapp"]


# ── Health ────────────────────────────────────────────────────────────────────

def register_health_routes(app) -> None:
    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        m = _webapp_module()
        free_space = await asyncio.to_thread(get_free_space, m.DOCS_ROOT.parent)
        return {
            "status": "healthy",
            "version": m.API_VERSION,
            "docs_root": str(m.DOCS_ROOT),
            "free_space_bytes": free_space,
            "free_space_human": format_bytes(free_space),
        }


# ── Storage ───────────────────────────────────────────────────────────────────

def register_storage_routes(app) -> None:
    @app.get("/storage/info")
    async def storage_info(request: Request, x_api_key: str | None = Header(None)):
        """Get server storage details and model factory diagnostics."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        m = _webapp_module()
        total, used, free = await asyncio.to_thread(shutil.disk_usage, str(m.DOCS_ROOT.parent))

        model_diagnostics = await run_model_diagnostics()

        return {
            "storage": {
                "total_space_bytes": total,
                "used_space_bytes": used,
                "free_space_bytes": free,
                "total_space_human": format_bytes(total),
                "used_space_human": format_bytes(used),
                "free_space_human": format_bytes(free),
                "usage_percentage": round((used / total) * 100, 2) if total > 0 else 0,
            },
            "model_factory": model_diagnostics,
            "environment_variables": dict(os.environ),
        }


# ── Document CRUD ─────────────────────────────────────────────────────────────

def register_document_routes(app) -> None:
    @app.post("/documents/upload", status_code=status.HTTP_201_CREATED)
    async def upload_documents(
            request: Request,
            folder: str = Form("policy"),
            files: list[UploadFile] = File(...),
            x_api_key: str | None = Header(None),
    ) -> dict:
        """Upload documents to a specified folder within docs directory."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        m = _webapp_module()
        relative_folder = safe_relative_folder(folder)
        destination_dir = m.DOCS_ROOT.joinpath(*relative_folder.parts)
        await asyncio.to_thread(destination_dir.mkdir, parents=True, exist_ok=True)

        saved: list[dict[str, Any]] = []
        total_uploaded_size = 0
        for upload in files:
            filename = safe_filename(upload.filename)
            content = await upload.read()
            destination = destination_dir / filename
            await asyncio.to_thread(destination.write_bytes, content)
            file_size = len(content)
            total_uploaded_size += file_size
            saved.append({
                "filename": filename,
                "path": str(PurePosixPath("docs", *relative_folder.parts, filename)),
                "size": file_size,
            })

        free_space = await asyncio.to_thread(get_free_space, m.DOCS_ROOT.parent)

        # Auto-trigger wiki ingest for thread folders
        thread_id = extract_thread_id_from_folder(str(relative_folder))
        if thread_id:
            asyncio.create_task(
                trigger_wiki_auto_ingest(thread_id),
                name=f"wiki-auto-ingest-trigger-{thread_id}",
            )

        return {
            "folder": str(relative_folder),
            "count": len(saved),
            "saved": saved,
            "total_uploaded_bytes": total_uploaded_size,
            "free_space_bytes": free_space,
            "free_space_human": format_bytes(free_space),
        }

    @app.get("/documents/list")
    async def list_documents(
            request: Request,
            folder: str = "policy",
            x_api_key: str | None = Header(None),
    ) -> dict:
        """List all files in a specified folder within docs directory."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        m = _webapp_module()
        relative_folder = safe_relative_folder(folder)
        target_dir = m.DOCS_ROOT.joinpath(*relative_folder.parts)

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

        def _list_items():
            res = []
            for item in target_dir.iterdir():
                if item.is_file():
                    res.append({"name": item.name, "type": "file", "size": item.stat().st_size})
                elif item.is_dir():
                    res.append({"name": item.name, "type": "folder", "size": None})
            return res

        items = await asyncio.to_thread(_list_items)
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
        """Download a specific file from a folder."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        safe_name = safe_filename(filename)
        m = _webapp_module()
        relative_folder = safe_relative_folder(folder)
        file_path = m.DOCS_ROOT.joinpath(*relative_folder.parts, safe_name)

        if not (await asyncio.to_thread(file_path.exists)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File '{filename}' not found in folder '{folder}'",
            )

        if not (await asyncio.to_thread(file_path.is_file)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{filename}' is not a file",
            )

        return FileResponse(
            path=file_path,
            filename=safe_name,
            media_type=detect_media_type(file_path),
        )

    @app.delete("/documents/{filename}", status_code=status.HTTP_200_OK)
    async def delete_document(
            request: Request,
            filename: str,
            folder: str = "policy",
            x_api_key: str | None = Header(None),
    ) -> dict:
        """Delete a specific file from a folder."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        safe_name = safe_filename(filename)
        m = _webapp_module()
        relative_folder = safe_relative_folder(folder)
        file_path = m.DOCS_ROOT.joinpath(*relative_folder.parts, safe_name)

        if not (await asyncio.to_thread(file_path.exists)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File '{filename}' not found in folder '{folder}'",
            )

        if not (await asyncio.to_thread(file_path.is_file)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{filename}' is not a file",
            )

        await asyncio.to_thread(file_path.unlink)

        # Trigger wiki delete hooks for thread folders
        thread_id = extract_thread_id_from_folder(str(relative_folder))
        if thread_id:
            asyncio.create_task(
                trigger_wiki_delete_hooks(thread_id, deleted_filename=safe_name),
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
        """Delete all files in a specified folder."""
        if not is_authenticated(x_api_key, request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API key. Provide X-API-Key header or Authorization header.",
            )

        m = _webapp_module()
        relative_folder = safe_relative_folder(folder)
        target_dir = m.DOCS_ROOT.joinpath(*relative_folder.parts)

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

        def _delete_files():
            deleted_count = 0
            for item in target_dir.iterdir():
                if item.is_file():
                    item.unlink()
                    deleted_count += 1
            return deleted_count

        deleted_count = await asyncio.to_thread(_delete_files)

        # Trigger wiki delete hooks for thread folders
        thread_id = extract_thread_id_from_folder(str(relative_folder))
        if thread_id:
            asyncio.create_task(
                trigger_wiki_delete_hooks(thread_id),
                name=f"wiki-folder-delete-hook-{thread_id}",
            )

        return {
            "message": f"All files deleted from folder '{folder}'",
            "folder": str(relative_folder),
            "deleted_count": deleted_count,
        }


# ── OAuth Authentication ──────────────────────────────────────────────────────

def register_oauth_routes(app) -> None:
    @app.get("/auth/login/{provider}")
    async def oauth_login(provider: str, request: Request):
        """Initiate OAuth login with Google or GitHub."""
        if not _cfg.OAUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth authentication is not enabled. Install required dependencies.",
            )

        if provider not in ("google", "github"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported OAuth provider: {provider}. Use 'google' or 'github'.",
            )

        forwarded_proto = request.headers.get("x-forwarded-proto", "http")
        forwarded_host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        base_url = (
            f"{forwarded_proto}://{forwarded_host}"
            if forwarded_host
            else str(request.base_url).rstrip("/")
        )
        redirect_uri = f"{base_url}/auth/callback/{provider}"

        try:
            login_url = await _cfg.get_oauth_login_url(request, provider, redirect_uri)
            return RedirectResponse(url=login_url)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to generate login URL: {e!s}",
            )

    @app.get("/auth/callback/{provider}")
    async def oauth_callback(provider: str, request: Request):
        """Handle OAuth callback from Google or GitHub."""
        if not _cfg.OAUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth authentication is not enabled.",
            )

        if provider not in ("google", "github"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported OAuth provider: {provider}.",
            )

        try:
            if provider == "google":
                user_data = await _cfg.handle_google_callback(request)
            else:
                user_data = await _cfg.handle_github_callback(request)

            frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
            session_token = user_data["session_token"]
            return RedirectResponse(url=f"{frontend_url}/login/success?token={session_token}")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"OAuth authentication failed: {e!s}",
            )

    @app.get("/auth/session/validate")
    async def validate_session(request: Request, x_api_key: str | None = Header(None)):
        """Validate an OAuth session token."""
        if not _cfg.OAUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth authentication is not enabled.",
            )

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

        user_data = _cfg.user_manager.validate_session(token)
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
                if k not in {
                    "identity", "email", "name", "provider",
                    "picture", "avatar_url", "raw_token", "session_token",
                }
            },
        }

    @app.post("/auth/session/refresh")
    async def refresh_session(request: Request, x_api_key: str | None = Header(None)):
        """Refresh (extend) an OAuth session token by 24 hours."""
        if not _cfg.OAUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth authentication is not enabled.",
            )

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

        user_data = _cfg.user_manager.refresh_session(token)
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
        }

    @app.post("/auth/logout")
    async def logout(request: Request, x_api_key: str | None = Header(None)):
        """Logout user by invalidating their OAuth session token."""
        if not _cfg.OAUTH_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OAuth authentication is not enabled.",
            )

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

        identity = _cfg.handle_logout(token)
        if not identity:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already expired.",
            )

        # Clean up the logged users tracking in auth module
        try:
            from auth import _logged_oauth_users

            if identity in _logged_oauth_users:
                _logged_oauth_users.discard(identity)
                print(f"✅ Cleaned up logged user tracking for: {identity}")
        except ImportError:
            pass

        return {
            "success": True,
            "message": "Successfully logged out",
            "identity": identity,
        }


# ── Convenience: register everything at once ────────────────────────────────────

def register_all_routes(app) -> None:
    """Register health, storage, document, and OAuth routes on *app*."""
    register_health_routes(app)
    register_storage_routes(app)
    register_document_routes(app)
    register_oauth_routes(app)
