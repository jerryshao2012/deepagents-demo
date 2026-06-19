"""Database abstraction for threads/runs across SQLite, PostgreSQL, and CosmosDB."""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from typing import Any

CREATE_THREADS_TABLE = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state_updated_at TEXT,
    messages TEXT NOT NULL DEFAULT '[]',
    values_ TEXT NOT NULL DEFAULT '{}',
    metadata TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'idle',
    user_id TEXT
);
"""

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES threads(thread_id),
    assistant_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    kwargs TEXT NOT NULL DEFAULT '{}',
    multitask_strategy TEXT NOT NULL DEFAULT 'enqueue',
    error TEXT
);
"""

_sqlite_lock = threading.Lock()
_sqlite_conn = None
_postgres_pool = None
_cosmos_threads_container = None
_cosmos_runs_container = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _thread_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    messages = _safe_json_loads(row.get("messages"), [])
    values = _safe_json_loads(row.get("values") if "values" in row else row.get("values_json"), {})
    metadata = _safe_json_loads(row.get("metadata"), {})
    if "messages" not in values:
        values["messages"] = messages
    return {
        "thread_id": row["thread_id"],
        "created_at": row["created_at"],
        "updated_at": row.get("updated_at") or row["created_at"],
        "state_updated_at": row.get("state_updated_at"),
        "messages": messages,
        "values": values,
        "metadata": metadata,
        "status": row.get("status") or "idle",
        "user_id": row.get("user_id"),
    }


def _run_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "thread_id": row["thread_id"],
        "assistant_id": row["assistant_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row.get("updated_at") or row["created_at"],
        "metadata": _safe_json_loads(row.get("metadata"), {}),
        "kwargs": _safe_json_loads(row.get("kwargs"), {}),
        "multitask_strategy": row.get("multitask_strategy") or "enqueue",
        "error": row.get("error"),
    }


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

        thread_cols = {row[1] for row in conn.execute("PRAGMA table_info(threads)").fetchall()}
        if "updated_at" not in thread_cols:
            conn.execute("ALTER TABLE threads ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE threads SET updated_at = created_at WHERE updated_at IS NULL")
        if "state_updated_at" not in thread_cols:
            conn.execute("ALTER TABLE threads ADD COLUMN state_updated_at TEXT")
        if "metadata" not in thread_cols:
            conn.execute("ALTER TABLE threads ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        if "status" not in thread_cols:
            conn.execute("ALTER TABLE threads ADD COLUMN status TEXT NOT NULL DEFAULT 'idle'")

        run_cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "updated_at" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN updated_at TEXT")
            conn.execute("UPDATE runs SET updated_at = created_at WHERE updated_at IS NULL")
        if "metadata" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        if "kwargs" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN kwargs TEXT NOT NULL DEFAULT '{}'")
        if "multitask_strategy" not in run_cols:
            conn.execute("ALTER TABLE runs ADD COLUMN multitask_strategy TEXT NOT NULL DEFAULT 'enqueue'")

        conn.commit()


def _init_postgres() -> None:
    global _postgres_pool
    if _postgres_pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise ImportError(
                "PostgreSQL driver missing. Install psycopg and psycopg_pool."
            ) from exc

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

    with _postgres_pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_THREADS_TABLE)
            cur.execute(CREATE_RUNS_TABLE)
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS updated_at TEXT")
            cur.execute("UPDATE threads SET updated_at = created_at WHERE updated_at IS NULL")
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS state_updated_at TEXT")
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS metadata TEXT NOT NULL DEFAULT '{}'")
            cur.execute("ALTER TABLE threads ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'idle'")
            cur.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS updated_at TEXT")
            cur.execute("UPDATE runs SET updated_at = created_at WHERE updated_at IS NULL")
            cur.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS metadata TEXT NOT NULL DEFAULT '{}'")
            cur.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS kwargs TEXT NOT NULL DEFAULT '{}'")
            cur.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS multitask_strategy TEXT NOT NULL DEFAULT 'enqueue'")


def _init_cosmos_db() -> None:
    global _cosmos_threads_container, _cosmos_runs_container
    if _cosmos_threads_container is not None:
        return

    try:
        from azure.cosmos import CosmosClient, PartitionKey
    except ImportError as exc:
        raise ImportError("Azure Cosmos SDK missing. Install azure-cosmos.") from exc

    endpoint = os.environ.get("COSMOSDB_ENDPOINT")
    key = os.environ.get("COSMOSDB_KEY")
    conn_str = os.environ.get("COSMOS_CONNECTION_STRING")
    db_name = os.environ.get("COSMOSDB_DB_NAME", "deep_research")

    if conn_str:
        client = CosmosClient.from_connection_string(conn_str)
    elif endpoint and key:
        client = CosmosClient(endpoint, credential=key)
    else:
        raise ValueError("Cosmos configuration missing.")

    db_client = client.create_database_if_not_exists(id=db_name)
    _cosmos_threads_container = db_client.create_container_if_not_exists(
        id="threads", partition_key=PartitionKey(path="/id")
    )
    _cosmos_runs_container = db_client.create_container_if_not_exists(
        id="runs", partition_key=PartitionKey(path="/id")
    )


def init_db() -> None:
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
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            row = conn.execute(
                "SELECT thread_id, created_at, updated_at, state_updated_at, messages, values_ AS values_json, metadata, status, user_id "
                "FROM threads WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        return _thread_to_dict(dict(row))

    if db_type == "postgres":
        from psycopg.rows import dict_row

        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT thread_id, created_at, updated_at, state_updated_at, messages, values_ AS values_json, metadata, status, user_id "
                    "FROM threads WHERE thread_id = %s",
                    (thread_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _thread_to_dict(dict(row))

    try:
        item = _cosmos_threads_container.read_item(item=thread_id, partition_key=thread_id)
    except Exception:
        return None

    return _thread_to_dict(
        {
            "thread_id": item["id"],
            "created_at": item["created_at"],
            "updated_at": item.get("updated_at"),
            "state_updated_at": item.get("state_updated_at"),
            "messages": item.get("messages", []),
            "values": item.get("values", {}),
            "metadata": item.get("metadata", {}),
            "status": item.get("status", "idle"),
            "user_id": item.get("user_id"),
        }
    )


def create_thread(
        thread_id: str,
        user_id: str,
        created_at: str,
        metadata: dict[str, Any] | None = None,
        status: str = "idle",
        values: dict[str, Any] | None = None,
) -> None:
    metadata = metadata or {}
    values = dict(values or {})
    values.setdefault("messages", [])

    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "INSERT INTO threads (thread_id, created_at, updated_at, state_updated_at, messages, values_, metadata, status, user_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    created_at,
                    created_at,
                    created_at,
                    json.dumps(values.get("messages", [])),
                    json.dumps(values),
                    json.dumps(metadata),
                    status,
                    user_id,
                ),
            )
            conn.commit()
        return

    if db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO threads (thread_id, created_at, updated_at, state_updated_at, messages, values_, metadata, status, user_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        thread_id,
                        created_at,
                        created_at,
                        created_at,
                        json.dumps(values.get("messages", [])),
                        json.dumps(values),
                        json.dumps(metadata),
                        status,
                        user_id,
                    ),
                )
        return

    _cosmos_threads_container.create_item(
        body={
            "id": thread_id,
            "created_at": created_at,
            "updated_at": created_at,
            "state_updated_at": created_at,
            "messages": values.get("messages", []),
            "values": values,
            "metadata": metadata,
            "status": status,
            "user_id": user_id,
        }
    )


def update_thread(
        thread_id: str,
        messages: list,
        values: dict,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        updated_at: str | None = None,
) -> None:
    current = get_thread(thread_id)
    if current is None:
        return

    next_values = dict(values or {})
    next_values["messages"] = messages
    next_metadata = current.get("metadata", {}) if metadata is None else metadata
    next_status = status or current.get("status") or "idle"
    now = updated_at or _now_iso()

    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "UPDATE threads SET messages = ?, values_ = ?, metadata = ?, status = ?, updated_at = ?, state_updated_at = ? WHERE thread_id = ?",
                (
                    json.dumps(messages),
                    json.dumps(next_values),
                    json.dumps(next_metadata),
                    next_status,
                    now,
                    now,
                    thread_id,
                ),
            )
            conn.commit()
        return

    if db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE threads SET messages = %s, values_ = %s, metadata = %s, status = %s, updated_at = %s, state_updated_at = %s WHERE thread_id = %s",
                    (
                        json.dumps(messages),
                        json.dumps(next_values),
                        json.dumps(next_metadata),
                        next_status,
                        now,
                        now,
                        thread_id,
                    ),
                )
        return

    item = _cosmos_threads_container.read_item(item=thread_id, partition_key=thread_id)
    item["messages"] = messages
    item["values"] = next_values
    item["metadata"] = next_metadata
    item["status"] = next_status
    item["updated_at"] = now
    item["state_updated_at"] = now
    _cosmos_threads_container.upsert_item(body=item)


def update_thread_metadata(thread_id: str, metadata: dict[str, Any]) -> bool:
    thread = get_thread(thread_id)
    if thread is None:
        return False

    merged = dict(thread.get("metadata") or {})
    merged.update(metadata or {})
    now = _now_iso()

    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "UPDATE threads SET metadata = ?, updated_at = ? WHERE thread_id = ?",
                (json.dumps(merged), now, thread_id),
            )
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE threads SET metadata = %s, updated_at = %s WHERE thread_id = %s",
                    (json.dumps(merged), now, thread_id),
                )
    else:
        item = _cosmos_threads_container.read_item(item=thread_id, partition_key=thread_id)
        item["metadata"] = merged
        item["updated_at"] = now
        _cosmos_threads_container.upsert_item(body=item)

    return True


def update_thread_state(thread_id: str, values: dict[str, Any]) -> bool:
    thread = get_thread(thread_id)
    if thread is None:
        return False

    merged_values = dict(thread.get("values") or {})
    merged_values.update(values or {})
    messages = merged_values.get("messages") or thread.get("messages") or []
    update_thread(
        thread_id,
        messages,
        merged_values,
        metadata=thread.get("metadata") or {},
        status=thread.get("status") or "idle",
    )
    return True


def delete_thread(thread_id: str) -> bool:
    thread = get_thread(thread_id)
    if thread is None:
        return False

    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute("DELETE FROM runs WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))
            conn.commit()
    elif db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM runs WHERE thread_id = %s", (thread_id,))
                cur.execute("DELETE FROM threads WHERE thread_id = %s", (thread_id,))
    else:
        _cosmos_threads_container.delete_item(item=thread_id, partition_key=thread_id)
        query = "SELECT c.id FROM c WHERE c.thread_id = @thread_id"
        parameters = [{"name": "@thread_id", "value": thread_id}]
        for item in _cosmos_runs_container.query_items(
                query=query, parameters=parameters, enable_cross_partition_query=True
        ):
            _cosmos_runs_container.delete_item(item=item["id"], partition_key=item["id"])

    return True


def search_threads(
        *,
        limit: int = 10,
        offset: int = 0,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 10), 1000))
    offset = max(0, int(offset or 0))
    sort_by = sort_by if sort_by in {"thread_id", "status", "created_at", "updated_at",
                                     "state_updated_at"} else "updated_at"
    sort_order = "asc" if (sort_order or "").lower() == "asc" else "desc"
    metadata = metadata or {}

    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    items: list[dict[str, Any]]

    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            rows = conn.execute(
                f"SELECT thread_id, created_at, updated_at, state_updated_at, messages, values_ AS values_json, metadata, status, user_id "
                f"FROM threads ORDER BY {sort_by} {sort_order}"
            ).fetchall()
        items = [_thread_to_dict(dict(row)) for row in rows]
    elif db_type == "postgres":
        from psycopg.rows import dict_row

        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT thread_id, created_at, updated_at, state_updated_at, messages, values_ AS values_json, metadata, status, user_id "
                    f"FROM threads ORDER BY {sort_by} {sort_order}"
                )
                rows = cur.fetchall()
        items = [_thread_to_dict(dict(row)) for row in rows]
    else:
        rows = list(_cosmos_threads_container.query_items(query="SELECT * FROM c", enable_cross_partition_query=True))
        items = [
            _thread_to_dict(
                {
                    "thread_id": item["id"],
                    "created_at": item["created_at"],
                    "updated_at": item.get("updated_at"),
                    "state_updated_at": item.get("state_updated_at"),
                    "messages": item.get("messages", []),
                    "values": item.get("values", {}),
                    "metadata": item.get("metadata", {}),
                    "status": item.get("status", "idle"),
                    "user_id": item.get("user_id"),
                }
            )
            for item in rows
        ]
        items.sort(key=lambda x: x.get(sort_by) or "", reverse=(sort_order == "desc"))

    def _match(item: dict[str, Any]) -> bool:
        if status is not None and item.get("status") != status:
            return False
        if user_id and item.get("user_id") not in {None, "", user_id}:
            return False
        existing_meta = item.get("metadata") or {}
        for k, v in metadata.items():
            if existing_meta.get(k) != v:
                return False
        return True

    filtered = [item for item in items if _match(item)]
    return filtered[offset: offset + limit]


def get_run(run_id: str) -> dict[str, Any] | None:
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            row = conn.execute(
                "SELECT run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error "
                "FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _run_to_dict(dict(row))

    if db_type == "postgres":
        from psycopg.rows import dict_row

        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error "
                    "FROM runs WHERE run_id = %s",
                    (run_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _run_to_dict(dict(row))

    try:
        item = _cosmos_runs_container.read_item(item=run_id, partition_key=run_id)
    except Exception:
        return None

    return _run_to_dict(
        {
            "run_id": item["id"],
            "thread_id": item["thread_id"],
            "assistant_id": item["assistant_id"],
            "status": item["status"],
            "created_at": item["created_at"],
            "updated_at": item.get("updated_at"),
            "metadata": item.get("metadata", {}),
            "kwargs": item.get("kwargs", {}),
            "multitask_strategy": item.get("multitask_strategy", "enqueue"),
            "error": item.get("error"),
        }
    )


def list_runs(thread_id: str, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 10), 1000))
    offset = max(0, int(offset or 0))
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            rows = conn.execute(
                "SELECT run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error "
                "FROM runs WHERE thread_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (thread_id, limit, offset),
            ).fetchall()
        return [_run_to_dict(dict(row)) for row in rows]

    if db_type == "postgres":
        from psycopg.rows import dict_row

        with _postgres_pool.connection() as conn:
            conn.row_factory = dict_row
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error "
                    "FROM runs WHERE thread_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (thread_id, limit, offset),
                )
                rows = cur.fetchall()
        return [_run_to_dict(dict(row)) for row in rows]

    items = list(
        _cosmos_runs_container.query_items(
            query="SELECT * FROM c WHERE c.thread_id = @thread_id",
            parameters=[{"name": "@thread_id", "value": thread_id}],
            enable_cross_partition_query=True,
        )
    )
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return [
        _run_to_dict(
            {
                "run_id": item["id"],
                "thread_id": item["thread_id"],
                "assistant_id": item["assistant_id"],
                "status": item["status"],
                "created_at": item["created_at"],
                "updated_at": item.get("updated_at"),
                "metadata": item.get("metadata", {}),
                "kwargs": item.get("kwargs", {}),
                "multitask_strategy": item.get("multitask_strategy", "enqueue"),
                "error": item.get("error"),
            }
        )
        for item in items[offset: offset + limit]
    ]


def create_run(
        run_id: str,
        thread_id: str,
        assistant_id: str,
        created_at: str,
        multitask_strategy: str | None = None,
) -> None:
    strategy = multitask_strategy or "enqueue"
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "INSERT INTO runs (run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    thread_id,
                    assistant_id,
                    "pending",
                    created_at,
                    created_at,
                    json.dumps({}),
                    json.dumps({}),
                    strategy,
                    None,
                ),
            )
            conn.commit()
        return

    if db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO runs (run_id, thread_id, assistant_id, status, created_at, updated_at, metadata, kwargs, multitask_strategy, error) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        run_id,
                        thread_id,
                        assistant_id,
                        "pending",
                        created_at,
                        created_at,
                        json.dumps({}),
                        json.dumps({}),
                        strategy,
                        None,
                    ),
                )
        return

    _cosmos_runs_container.create_item(
        body={
            "id": run_id,
            "thread_id": thread_id,
            "assistant_id": assistant_id,
            "status": "pending",
            "created_at": created_at,
            "updated_at": created_at,
            "metadata": {},
            "kwargs": {},
            "multitask_strategy": strategy,
            "error": None,
        }
    )


def update_run_status(run_id: str, status: str, error: str | None = None) -> None:
    now = _now_iso()
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE run_id = ?",
                (status, error, now, run_id),
            )
            conn.commit()
        return

    if db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE runs SET status = %s, error = %s, updated_at = %s WHERE run_id = %s",
                    (status, error, now, run_id),
                )
        return

    item = _cosmos_runs_container.read_item(item=run_id, partition_key=run_id)
    item["status"] = status
    item["updated_at"] = now
    if error is not None:
        item["error"] = error
    _cosmos_runs_container.upsert_item(body=item)


def cancel_running_runs(thread_id: str) -> None:
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()

    if db_type == "sqlite":
        with _sqlite_lock:
            conn = _get_sqlite_conn()
            conn.execute(
                "UPDATE runs SET status = 'cancelled', updated_at = ? WHERE thread_id = ? AND status = 'running'",
                (_now_iso(), thread_id),
            )
            conn.commit()
        return

    if db_type == "postgres":
        with _postgres_pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE runs SET status = 'cancelled', updated_at = %s WHERE thread_id = %s AND status = 'running'",
                    (_now_iso(), thread_id),
                )
        return

    items = list(
        _cosmos_runs_container.query_items(
            query="SELECT * FROM c WHERE c.thread_id = @thread_id AND c.status = 'running'",
            parameters=[{"name": "@thread_id", "value": thread_id}],
            enable_cross_partition_query=True,
        )
    )
    for item in items:
        item["status"] = "cancelled"
        item["updated_at"] = _now_iso()
        _cosmos_runs_container.upsert_item(body=item)
