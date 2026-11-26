"""Agent Profile metadata database (agent-meta.sqlite).

Independent of the checkpoint DB. Stores profile metadata, run records,
and memory entries/candidates.
"""
from __future__ import annotations

import datetime
import sqlite3
import threading
from pathlib import Path

from src.profiles.schema import AgentProfile

META_DB_NAME = "agent-meta.sqlite"

# In-process write-lock registry: one threading.Lock per resolved database
# path.  SQLite's busy_timeout still covers cross-process contention; this
# makes in-process threads sharing one agent-meta.sqlite wait on a Python
# lock instead of the 30s busy timeout (throttled CI runners could exceed
# it and flake with OperationalError('database is locked')).  Entries are
# dropped when no longer held, so the registry stays bounded.
_write_locks: dict[str, threading.Lock] = {}
_write_locks_guard = threading.Lock()


def db_write_lock(db_path) -> threading.Lock:
    """Process-local lock guarding writes to one database file.

    Keyed by the resolved path so alias spellings of the same file share
    one lock.  Cross-process safety remains SQLite's busy_timeout; this
    only removes in-process contention (CI flake, run 45779817244).
    """
    key = str(Path(db_path).resolve())
    with _write_locks_guard:
        lock = _write_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _write_locks[key] = lock
        return lock


def release_db_write_lock(db_path) -> None:
    """Release and forget db_path's lock (call once per acquire).

    The registry entry is dropped only when this call still owns the lock
    (verified with a non-blocking acquire), so a racing holder is never
    disturbed; the registry stays bounded across throwaway test homes.
    """
    key = str(Path(db_path).resolve())
    with _write_locks_guard:
        lock = _write_locks.get(key)
        if lock is None:
            return
        if lock.acquire(blocking=False):
            lock.release()
            _write_locks.pop(key, None)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def meta_db_path(user_home: Path) -> Path:
    """Path to agent-meta.sqlite under user_home."""
    return user_home / META_DB_NAME


_DDL_VERSION_1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_profiles (
    profile_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    profile_version INTEGER NOT NULL,
    profile_hash TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    runtime_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    profile_hash TEXT NOT NULL,
    task_id TEXT,
    session_id TEXT,
    project_id TEXT,
    workspace TEXT,
    engine TEXT NOT NULL DEFAULT 'deepagents',
    status TEXT NOT NULL DEFAULT 'created',
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS memory_entries (
    memory_id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_task_id TEXT,
    source_agent_id TEXT,
    project_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_candidates (
    candidate_id TEXT PRIMARY KEY,
    target_namespace TEXT NOT NULL,
    source_task_id TEXT,
    source_agent_id TEXT,
    content TEXT NOT NULL,
    source_reference TEXT,
    status TEXT NOT NULL DEFAULT 'pending_review',
    created_at TEXT NOT NULL,
    reviewed_at TEXT,
    reviewed_by TEXT
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply pending migrations (idempotent, serialized).

    The whole read-apply block runs under BEGIN IMMEDIATE so concurrent
    migrators on the same database serialize: each one observes the
    version markers published by the previous one before deciding what
    to apply.  Version inserts use OR IGNORE so a double-apply can
    never raise a UNIQUE violation.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        rows = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchall()
        max_v = rows[0][0] if rows and rows[0][0] is not None else 0
        if max_v < 1:
            for stmt in _DDL_VERSION_1.split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at) VALUES (1, ?)",
                (_utc_now(),),
            )
            max_v = 1
        if max_v < 2:
            # ticket 04: candidate records carry memory_type + confidence
            # (confidence nullable by design - never fabricated).
            cols = {r[1] for r in conn.execute("PRAGMA table_info(memory_candidates)")}
            if "memory_type" not in cols:
                conn.execute(
                    "ALTER TABLE memory_candidates "
                    "ADD COLUMN memory_type TEXT NOT NULL DEFAULT ''"
                )
            if "confidence" not in cols:
                conn.execute(
                    "ALTER TABLE memory_candidates "
                    "ADD COLUMN confidence TEXT"
                )
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations "
                "(version, applied_at) VALUES (2, ?)",
                (_utc_now(),),
            )
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise


def connect(user_home: Path) -> sqlite3.Connection:
    """Open (or create) agent-meta.sqlite and run migrations."""
    user_home.mkdir(parents=True, exist_ok=True)
    db_path = meta_db_path(user_home)
    lock = db_write_lock(db_path)
    lock.acquire()
    try:
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA journal_mode=WAL")
        _migrate(conn)
    finally:
        lock.release()
        release_db_write_lock(db_path)
    return conn


def upsert_profile(
    user_home: Path,
    profile: AgentProfile,
    profile_hash: str,
    source_path: str = "",
) -> None:
    """Insert or update a profile row in agent_profiles."""
    lock = db_write_lock(meta_db_path(user_home))
    conn = connect(user_home)
    lock.acquire()
    try:
        now = _utc_now()
        conn.execute(
            """INSERT INTO agent_profiles
               (profile_id, schema_version, profile_version, profile_hash, source_path,
                enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(profile_id) DO UPDATE SET
                 schema_version = excluded.schema_version,
                 profile_version = excluded.profile_version,
                 profile_hash = excluded.profile_hash,
                 source_path = excluded.source_path,
                 enabled = 1,
                 updated_at = excluded.updated_at""",
            (
                profile.id,
                profile.schema_version,
                profile.profile_version,
                profile_hash,
                source_path,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        lock.release()
        release_db_write_lock(meta_db_path(user_home))
        conn.close()


def list_profile_rows(user_home: Path) -> list[dict]:
    """Return all agent_profiles rows as dict list (for tests)."""
    conn = connect(user_home)
    try:
        rows = conn.execute(
            "SELECT profile_id, schema_version, profile_version, profile_hash, "
            "source_path, enabled, created_at, updated_at FROM agent_profiles ORDER BY profile_id"
        ).fetchall()
        cols = ("profile_id", "schema_version", "profile_version", "profile_hash",
                "source_path", "enabled", "created_at", "updated_at")
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


_RUN_COLS = (
    "runtime_id", "profile_id", "profile_version", "profile_hash", "task_id",
    "session_id", "project_id", "workspace", "engine", "status", "started_at",
    "finished_at",
)


def insert_agent_run(
    user_home: Path,
    *,
    runtime_id: str,
    profile_id: str,
    profile_version: int,
    profile_hash: str = "",
    task_id: str | None = None,
    session_id: str | None = None,
    project_id: str | None = None,
    workspace: str = "",
    engine: str = "deepagents",
    status: str = "created",
) -> None:
    """Insert an agent_runs row (idempotent: re-create refreshes in place)."""
    lock = db_write_lock(meta_db_path(user_home))
    conn = connect(user_home)
    lock.acquire()
    try:
        conn.execute(
            """INSERT INTO agent_runs
               (runtime_id, profile_id, profile_version, profile_hash, task_id,
                session_id, project_id, workspace, engine, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(runtime_id) DO UPDATE SET
                profile_id = excluded.profile_id,
                profile_version = excluded.profile_version,
                profile_hash = excluded.profile_hash,
                task_id = excluded.task_id,
                session_id = excluded.session_id,
                project_id = excluded.project_id,
                workspace = excluded.workspace,
                engine = excluded.engine,
                status = excluded.status,
                started_at = excluded.started_at""",
            (
                runtime_id,
                profile_id,
                profile_version,
                profile_hash,
                task_id,
                session_id,
                project_id,
                workspace,
                engine,
                status,
                _utc_now(),
            ),
        )
        conn.commit()
    finally:
        lock.release()
        release_db_write_lock(meta_db_path(user_home))
        conn.close()


def update_agent_run_status(
    user_home: Path,
    runtime_id: str,
    status: str,
    *,
    finished: bool = False,
) -> bool:
    """Update status (+ finished_at when finished=True). True if a row was hit."""
    lock = db_write_lock(meta_db_path(user_home))
    conn = connect(user_home)
    lock.acquire()
    try:
        if finished:
            cur = conn.execute(
                "UPDATE agent_runs SET status = ?, finished_at = ? WHERE runtime_id = ?",
                (status, _utc_now(), runtime_id),
            )
        else:
            cur = conn.execute(
                "UPDATE agent_runs SET status = ? WHERE runtime_id = ?",
                (status, runtime_id),
            )
        conn.commit()
        return cur.rowcount > 0
    finally:
        lock.release()
        release_db_write_lock(meta_db_path(user_home))
        conn.close()


def list_agent_run_rows(
    user_home: Path,
    *,
    profile_id: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """Return agent_runs rows (newest first) as dict list, optional filters."""
    conn = connect(user_home)
    try:
        sql = "SELECT " + ", ".join(_RUN_COLS) + " FROM agent_runs"
        clauses: list[str] = []
        args: list = []
        if profile_id is not None:
            clauses.append("profile_id = ?")
            args.append(profile_id)
        if status is not None:
            clauses.append("status = ?")
            args.append(status)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY started_at DESC, runtime_id"
        rows = conn.execute(sql, args).fetchall()
        return [dict(zip(_RUN_COLS, r)) for r in rows]
    finally:
        conn.close()
