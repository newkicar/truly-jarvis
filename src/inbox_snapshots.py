"""Inbox 写入快照：写入前记录，供会话 /rollback 还原。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.vault_guard import VAULT_WRITE_TOOLS, is_writable_vault_path, normalize_vault_path

from src.project_paths import RUNTIME_DATA_DIR

DB_NAME = "inbox_snapshots.sqlite"


def _db_path(root: Path) -> Path:
    path = Path(root).resolve() / RUNTIME_DATA_DIR / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS inbox_writes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "thread_id TEXT NOT NULL, "
        "checkpoint_id TEXT NOT NULL, "
        "virtual_path TEXT NOT NULL, "
        "pre_exists INTEGER NOT NULL, "
        "pre_content TEXT, "
        "ts TEXT DEFAULT (datetime('now')))"
    )
    conn.commit()


@contextmanager
def _db(root: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path(root))
    try:
        _init_db(conn)
        yield conn
    finally:
        conn.close()


def virtual_to_local(vault_root: Path, virtual_path: str) -> Path:
    norm = normalize_vault_path(virtual_path)
    if not norm.startswith("/vault/"):
        raise ValueError(f"非 vault 路径: {virtual_path}")
    rel = norm[len("/vault/") :].lstrip("/")
    return (Path(vault_root) / rel).resolve()


def read_pre_state(vault_root: Path, virtual_path: str) -> tuple[bool, str | None]:
    local = virtual_to_local(vault_root, virtual_path)
    if not local.exists():
        return False, None
    return True, local.read_text(encoding="utf-8")


def record_write(
    project_root: Path,
    *,
    thread_id: str,
    checkpoint_id: str,
    virtual_path: str,
    pre_exists: bool,
    pre_content: str | None,
) -> None:
    if not thread_id or not virtual_path:
        return
    root = Path(project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _db(root) as conn:
        conn.execute(
            "INSERT INTO inbox_writes "
            "(thread_id, checkpoint_id, virtual_path, pre_exists, pre_content) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                thread_id,
                checkpoint_id or "",
                normalize_vault_path(virtual_path),
                1 if pre_exists else 0,
                pre_content,
            ),
        )
        conn.commit()


def list_writes(project_root: Path, thread_id: str | None = None) -> list[dict]:
    with _db(project_root) as conn:
        if thread_id:
            rows = conn.execute(
                "SELECT id, thread_id, checkpoint_id, virtual_path, pre_exists, pre_content "
                "FROM inbox_writes WHERE thread_id = ? ORDER BY id ASC",
                (thread_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, thread_id, checkpoint_id, virtual_path, pre_exists, pre_content "
                "FROM inbox_writes ORDER BY id ASC"
            ).fetchall()
    return [
        {
            "id": r[0],
            "thread_id": r[1],
            "checkpoint_id": r[2],
            "virtual_path": r[3],
            "pre_exists": bool(r[4]),
            "pre_content": r[5],
        }
        for r in rows
    ]


def delete_writes_for_thread(project_root: Path, thread_id: str) -> int:
    """删除某会话的 Inbox 写入快照记录（不改动 vault 文件）。"""
    with _db(project_root) as conn:
        cur = conn.execute("DELETE FROM inbox_writes WHERE thread_id = ?", (thread_id,))
        conn.commit()
        return cur.rowcount


def _checkpoints_newer_than(agent, thread_id: str, target_checkpoint_id: str) -> set[str] | None:
    """返回严格新于 target 的 checkpoint_id 集合；target 不存在则 None。"""
    from src.commands import thread_config  # 与 commands.py 的延迟引用惯例保持一致

    newer: set[str] = set()
    found = False
    try:
        for state in agent.get_state_history(config=thread_config(thread_id)):
            cid = state.config.get("configurable", {}).get("checkpoint_id")
            if not cid:
                continue
            if cid == target_checkpoint_id:
                found = True
                break
            newer.add(cid)
    except Exception:
        return None
    return newer if found else None


def restore_inbox_for_rollback(
    project_root: Path,
    vault_root: Path,
    agent,
    thread_id: str,
    target_checkpoint_id: str,
) -> list[tuple[str, str]]:
    """还原该会话在 target 之后写过的 Inbox 文件。返回 [(virtual_path, 操作描述), ...]。"""
    if thread_id.startswith("sched-"):
        return []

    newer = _checkpoints_newer_than(agent, thread_id, target_checkpoint_id)
    if newer is None:
        return []

    writes = [
        w
        for w in list_writes(project_root, thread_id)
        if w["checkpoint_id"] in newer
    ]
    if not writes:
        return []

    # 每个路径取 target 之后**第一次**写入的写前状态
    first_by_path: dict[str, dict] = {}
    for w in writes:
        vp = w["virtual_path"]
        if vp not in first_by_path:
            first_by_path[vp] = w

    actions: list[tuple[str, str]] = []
    for vp, w in sorted(first_by_path.items()):
        local = virtual_to_local(vault_root, vp)
        if w["pre_exists"]:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(w["pre_content"] or "", encoding="utf-8")
            actions.append((vp, "还原"))
        elif local.exists():
            local.unlink()
            actions.append((vp, "删除"))

    return actions


def is_inbox_write_tool(tool: str, path: str) -> bool:
    return tool in VAULT_WRITE_TOOLS and is_writable_vault_path(path)
