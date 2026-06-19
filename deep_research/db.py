"""Database abstractor module supporting SQLite, CosmosDB, and PostgreSQL.

Configured via environment variables:
    DB_TYPE = sqlite | cosmosdb | postgres (default: sqlite)

Thread-safe implementation using locks for SQLite, connection pooling for PostgreSQL,
and cached client references for CosmosDB.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

# ── SQL Constants ─────────────────────────────────────────────────────────────

# Schema
CREATE_THREADS_TABLE = """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id  TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        messages   TEXT NOT NULL DEFAULT '[]',
        values_    TEXT NOT NULL DEFAULT '{}',
        user_id    TEXT
    );
"""
CREATE_RUNS_TABLE = """
    CREATE TABLE IF NOT EXISTS runs (
        run_id       TEXT PRIMARY KEY,
        thread_id    TEXT NOT NULL REFERENCES threads(thread_id),
        assistant_id TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'pending',
        created_at   TEXT NOT NULL,
        error        TEXT
    );
"""

# Threads
GET_THREAD_BY_ID = "SELECT thread_id, created_at, messages, values_, user_id FROM threads WHERE thread_id = ?"
GET_THREAD_BY_ID_POSTGRES = "SELECT thread_id, created_at, messages, values_ AS values, user_id FROM threads WHERE thread_id = %s"
INSERT_THREAD = "INSERT INTO threads (thread_id, created_at, user_id) VALUES (?, ?, ?)"
INSERT_THREAD_POSTGRES = "INSERT INTO threads (thread_id, created_at, user_id) VALUES (%s, %s, %s)"
UPDATE_THREAD = "UPDATE threads SET messages = ?, values_ = ? WHERE thread_id = ?"
UPDATE_THREAD_POSTGRES = "UPDATE threads SET messages = %s, values_ = %s WHERE thread_id = %s"

# Runs
GET_RUN_BY_ID = "SELECT run_id, thread_id, assistant_id, status, created_at, error FROM runs WHERE run_id = ?"
GET_RUN_BY_ID_POSTGRES = "SELECT run_id, thread_id, assistant_id, status, created_at, error FROM runs WHERE run_id = %s"
INSERT_RUN = "INSERT INTO runs (run_id, thread_id, assistant_id, created_at) VALUES (?, ?, ?, ?)"
INSERT_RUN_POSTGRES = "INSERT INTO runs (run_id, thread_id, assistant_id, created_at) VALUES (%s, %s, %s, %s)"
UPDATE_RUN_STATUS = "UPDATE runs SET status = ?, error = ? WHERE run_id = ?"
UPDATE_RUN_STATUS_POSTGRES = "UPDATE runs SET status = %s, error = %s WHERE run_id = %s"
CANCEL_RUNNING_RUNS = "UPDATE runs SET status = 'cancelled' WHERE thread_id = ? AND status = 'running'"
CANCEL_RUNNING_RUNS_POSTGRES = "UPDATE runs SET status = 'cancelled' WHERE thread_id = %s AND status = 'running'"

# SQLite locks for thread-safety (SQLite connections cannot execute concurrently)
_sqlite_lock = threading.Lock()

# Global client/connection/pool cache
_sqlite_conn = None
_postgres_pool = None

_cosmos_threads_container = None
_cosmos_runs_container = None


# ── SQLite Backend ────────────────────────────────────────────────────────────

def _get_sqlite_conn():
    global _sqlite_conn
    if _sqlite_conn is None:
        import sqlite3
        db_path = os.environ.get("SQLITE_DB_PATH", ":memory:")
        _sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
    return _sqlite_conn


def _init_sqlite() -> None:
    with _sqlite_lock:
        conn = _get_sqlite_conn()
        conn.executescript(f"{CREATE_THREADS_TABLE}{CREATE_RUNS_TABLE}")
        conn.commit()


# ── PostgreSQL Backend ────────────────────────────────────────────────────────

def _init_postgres() -> None:
    global _postgres_pool
    if _postgres_pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError:
            raise ImportError(
                "PostgreSQL driver 'psycopg' or pool 'psycopg_pool' not found. Please run 'pip install \"psycopg[binary]\"' or 'uv add \"psycopg[binary]\"'."
            )

        pg_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
        if pg_url:
            _postgres_pool = ConnectionPool(conninfo=pg_url, min_size=2, max_size=10, open=True)
        else:
            host = os.environ.get("POSTGRES_HOST", "localhost")
            port = os.environ.get("POSTGRES_PORT", "5432")
            user = os.environ.get("POSTGRES_USER", "postgres")
            password = os.environ.get("POSTGRES_PASSWORD", "")
            dbname = os.environ.get("POSTGRES_DB", "postgres")
            conninfo = f"host={host} port={port} user={user} password={password} dbname={dbname}"
            _postgres_pool = ConnectionPool(conninfo=conninfo, min_size=2, max_size=10, open=True)

    # Create tables using a pooled connection
    with _postgres_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_THREADS_TABLE)
            cur.execute(CREATE_RUNS_TABLE)


# ── CosmosDB Backend ──────────────────────────────────────────────────────────

def _init_cosmos_db():
    global _cosmos_threads_container, _cosmos_runs_container
    if _cosmos_threads_container is None:
        try:
            from azure.cosmos import CosmosClient, PartitionKey
        except ImportError:
            raise ImportError(
                "Azure Cosmos DB SDK 'azure-cosmos' not found. Please run 'pip install azure-cosmos' or 'uv add azure-cosmos'."
            )

        endpoint = os.environ.get("COSMOSDB_ENDPOINT")
        key = os.environ.get("COSMOSDB_KEY")
        conn_str = os.environ.get("COSMOS_CONNECTION_STRING")
        db_name = os.environ.get("COSMOSDB_DB_NAME", "deep_research")

        if conn_str:
            client = CosmosClient.from_connection_string(conn_str)
        elif endpoint and key:
            client = CosmosClient(endpoint, credential=key)
        else:
            try:
                from azure.identity import DefaultAzureCredential
                client = CosmosClient(endpoint, credential=DefaultAzureCredential())
            except Exception:
                raise ValueError(
                    "CosmosDB configuration missing. Set COSMOSDB_ENDPOINT and COSMOSDB_KEY, or COSMOS_CONNECTION_STRING."
                )

        db_client = client.create_database_if_not_exists(id=db_name)
        _cosmos_threads_container = db_client.create_container_if_not_exists(id="threads",
                                                                             partition_key=PartitionKey(path="/id"))
        _cosmos_runs_container = db_client.create_container_if_not_exists(id="runs",
                                                                          partition_key=PartitionKey(path="/id"))


# ── Public API ────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Initialize database schema/containers."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        _init_sqlite()
    elif db_type == "postgres":
        _init_postgres()
    elif db_type == "cosmosdb":
        _init_cosmos_db()
    else:
        raise ValueError(f"Unsupported DB_TYPE: {db_type}")


def get_thread(thread_id: str) -> dict[str, Any] | None:
    """Get thread by ID."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            row = conn.execute(GET_THREAD_BY_ID, (thread_id,)).fetchone()
            if row is None:
                return None
            return {
                "thread_id": row["thread_id"],
                "created_at": row["created_at"],
                "messages": json.loads(row["messages"]),
                "values": json.loads(row["values_"]),
                "user_id": row["user_id"],
            }
    elif db_type == "postgres":
        from psycopg.rows import dict_row
        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(GET_THREAD_BY_ID_POSTGRES, (thread_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                return {
                    "thread_id": row["thread_id"],
                    "created_at": row["created_at"],
                    "messages": json.loads(row["messages"]),
                    "values": json.loads(row["values"]),
                    "user_id": row["user_id"],
                }
    elif db_type == "cosmosdb":
        try:
            item = _cosmos_threads_container.read_item(item=thread_id, partition_key=thread_id)
            return {
                "thread_id": item["id"],
                "created_at": item["created_at"],
                "messages": item.get("messages", []),
                "values": item.get("values", {}),
                "user_id": item.get("user_id"),
            }
        except Exception:
            return None


def create_thread(thread_id: str, user_id: str, created_at: str) -> None:
    """Create a new thread."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(INSERT_THREAD, (thread_id, created_at, user_id))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(INSERT_THREAD_POSTGRES, (thread_id, created_at, user_id))
    elif db_type == "cosmosdb":
        _cosmos_threads_container.create_item(
            body={
                "id": thread_id,
                "created_at": created_at,
                "user_id": user_id,
                "messages": [],
                "values": {},
            }
        )


def update_thread(thread_id: str, messages: list, values: dict) -> None:
    """Update thread state."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(UPDATE_THREAD, (json.dumps(messages), json.dumps(values), thread_id))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(UPDATE_THREAD_POSTGRES, (json.dumps(messages), json.dumps(values), thread_id))
    elif db_type == "cosmosdb":
        item = _cosmos_threads_container.read_item(item=thread_id, partition_key=thread_id)
        item["messages"] = messages
        item["values"] = values
        _cosmos_threads_container.upsert_item(body=item)


def get_run(run_id: str) -> dict[str, Any] | None:
    """Get run by ID."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            row = conn.execute(GET_RUN_BY_ID, (run_id,)).fetchone()
            if row is None:
                return None
            return dict(row)
    elif db_type == "postgres":
        from psycopg.rows import dict_row
        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(GET_RUN_BY_ID_POSTGRES, (run_id,))
                row = cur.fetchone()
                if row is None:
                    return None
                return dict(row)
    elif db_type == "cosmosdb":
        try:
            item = _cosmos_runs_container.read_item(item=run_id, partition_key=run_id)
            return {
                "run_id": item["id"],
                "thread_id": item["thread_id"],
                "assistant_id": item["assistant_id"],
                "status": item["status"],
                "created_at": item["created_at"],
                "error": item.get("error"),
            }
        except Exception:
            return None


def create_run(run_id: str, thread_id: str, assistant_id: str, created_at: str) -> None:
    """Create a new run."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(INSERT_RUN, (run_id, thread_id, assistant_id, created_at))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(INSERT_RUN_POSTGRES, (run_id, thread_id, assistant_id, created_at))
    elif db_type == "cosmosdb":
        _cosmos_runs_container.create_item(
            body={
                "id": run_id,
                "thread_id": thread_id,
                "assistant_id": assistant_id,
                "status": "pending",
                "created_at": created_at,
            }
        )


def update_run_status(run_id: str, status: str, error: str | None = None) -> None:
    """Update status of a run."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(UPDATE_RUN_STATUS, (status, error, run_id))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(UPDATE_RUN_STATUS_POSTGRES, (status, error, run_id))
    elif db_type == "cosmosdb":
        item = _cosmos_runs_container.read_item(item=run_id, partition_key=run_id)
        item["status"] = status
        if error is not None:
            item["error"] = error
        _cosmos_runs_container.upsert_item(body=item)


def cancel_running_runs(thread_id: str) -> None:
    """Cancel all running runs for a thread."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(CANCEL_RUNNING_RUNS, (thread_id,))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(CANCEL_RUNNING_RUNS_POSTGRES, (thread_id,))
    elif db_type == "cosmosdb":
        query = "SELECT * FROM c WHERE c.thread_id = @thread_id AND c.status = 'running'"
        parameters = [{"name": "@thread_id", "value": thread_id}]
        items = list(
            _cosmos_runs_container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))
        for item in items:
            item["status"] = "cancelled"
            _cosmos_runs_container.upsert_item(body=item)
