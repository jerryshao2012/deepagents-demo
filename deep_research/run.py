#!/usr/bin/env python3
"""Development entry point for running the server with uvicorn using configured settings."""

import os
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    host = os.environ.get("UPLOAD_HOST", "0.0.0.0")
    port = int(os.environ.get("UPLOAD_PORT", "2024"))
    db_type = os.environ.get("DB_TYPE", "sqlite").strip().lower()
    sqlite_db_path = os.environ.get("SQLITE_DB_PATH", ":memory:")
    reload_enabled = os.environ.get("UVICORN_RELOAD", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    print(f"🎨 Starting Agent API Server on {host}:{port}")
    print(f"🚀 API: http://127.0.0.1:{port}")
    print(f"📚 API Docs: http://127.0.0.1:{port}/docs")

    if db_type in {"cosmosdb", "cosmos"}:
        print("Using Azure Cosmos DB backend (production deployment mode).")
    elif db_type in {"postgres", "postgresql"}:
        print("Using PostgreSQL backend (production deployment mode).")
    elif db_type == "sqlite" and sqlite_db_path == ":memory:":
        print("This in-memory database is designed for development and testing.")
        print("For production use, please use CosmosDB or PostgreSQL deployment.")
    elif db_type == "sqlite":
        print(f"Using SQLite file database at: {sqlite_db_path} (development/local mode).")
        print("For production use, CosmosDB or PostgreSQL is recommended.")
    else:
        print(f"Using database backend type: {db_type}.")

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=reload_enabled,
        reload_dirs=[str(project_root)],
        reload_excludes=[
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            "*.pyc",
            "*.pyo",
        ],
    )
