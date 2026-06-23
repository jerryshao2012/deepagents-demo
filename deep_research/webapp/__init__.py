"""webapp package — public API surface for the Document Upload API.

This module replaces the former monolithic ``webapp.py``.  It:

1. Creates and configures the FastAPI application instance.
2. Re-exports every public symbol that external code (``server.py``, tests)
   used to import from ``webapp.py`` so that no import path changes are needed.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

# ── Re-export public config symbols ──────────────────────────────────────────
from .config import (
    API_KEY,
    API_VERSION,
    DOCS_ROOT,
    FRONTEND_ORIGINS,
    OAUTH_ENABLED,
)

logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup / shutdown hooks."""
    try:
        import db
        db.init_db()
        print("✅ Database initialized via lifespan")
    except (ImportError, AttributeError):
        pass

    yield
    # (reserved for future shutdown logic)


# ── Application factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="Document Upload API",
    description="Upload documents to the deep research agent docs folder",
    version=API_VERSION,
    lifespan=_lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session middleware (for OAuth)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("OAUTH_SECRET_KEY", "oauth-session-secret-key-fallback-for-dev"),
)

# Thread-wiki routes (registered as a router, not inline functions)
from thread_wiki.routes import router as _wiki_router  # noqa: E402

app.include_router(_wiki_router)

# Register all webapp-owned routes
from .routes import register_all_routes  # noqa: E402

register_all_routes(app)


# ── __main__ support ──────────────────────────────────────────────────────────

def _main() -> None:
    """Entry point when running ``python -m webapp``."""
    import uvicorn

    host = os.environ.get("UPLOAD_HOST", "0.0.0.0")
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


if __name__ == "__main__":
    _main()
