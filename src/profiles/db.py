"""Agent Profile metadata database (agent-meta.sqlite).

Independent of the checkpoint DB. Stores profile metadata, run records,
and memory entries/candidates.
"""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

from src.profiles.schema import AgentProfile

META_DB_NAME = "agent-meta.sqlite"


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
    """Apply pending migrations (idempotent)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    rows = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchall()
    max_v = rows[0][0] if rows and rows[0][0] is not None else 0
    if max_v < 1:
        conn.executescript(_DDL_VERSION_1)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)",
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
            "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?)",
            (_utc_now(),),
        )
    conn.commit()


def connect(user_home: Path) -> sqlite3.Connection:
    """Open (or create) agent-meta.sqlite and run migrations."""
    user_home.mkdir(parents=True, exist_ok=True)
    db_path = meta_db_path(user_home)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate(conn)
    return conn


def upsert_profile(
    user_home: Path,
    profile: AgentProfile,
    profile_hash: str,
    source_path: str = "",
) -> None:
    """Insert or update a profile row in agent_profiles."""
    conn = connect(user_home)
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