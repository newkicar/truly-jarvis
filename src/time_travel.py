"""Time Travel 文件回退层（git 快照 + 映射表）。

会话回退由 checkpointer 原生完成（见 main.py 的 /replay /fork）；
本模块负责**文件状态回退**（设计文档 §10.3）：
- snapshot：项目目录有变更时，git add -A + commit，并记录 {thread_id, checkpoint_id, commit_hash}。
- rollback：按 checkpoint_id 找到对应 commit，git reset --hard 对齐会话回退。

仅作用于项目根仓库；vault 不纳入（独立 git 仓库，且依赖 Obsidian 恢复兜底）。
"""
import sqlite3
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from src.project_paths import RUNTIME_DATA_DIR

DB_NAME = "git_mapping.sqlite"

# 快照排除项依赖 .gitignore（checkpoints/ / .env 等）。


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=JARVIS",
            "-c",
            "user.email=jarvis@local",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _has_changes(root: Path) -> bool:
    """项目目录是否有未提交变更。"""
    return bool(_git(root, "status", "--porcelain"))


def _db_path(root: Path) -> Path:
    path = root / RUNTIME_DATA_DIR / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _init_db(root: Path):
    conn = sqlite3.connect(_db_path(root))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS snapshots ("
        "checkpoint_id TEXT PRIMARY KEY, "
        "thread_id TEXT, commit_hash TEXT, ts TEXT)"
    )
    conn.commit()
    return conn


@contextmanager
def _db(root: Path) -> Iterator[sqlite3.Connection]:
    """打开映射表连接，用完自动关闭。"""
    conn = _init_db(root)
    try:
        yield conn
    finally:
        conn.close()


def snapshot(root: Path, thread_id: str, checkpoint_id: str) -> Optional[str]:
    """若项目目录有变更则 git 提交并记录映射，返回 commit_hash；无变更返回 None。"""
    root = Path(root).resolve()
    if not (root / ".git").exists():
        return None
    if not _has_changes(root):
        return None

    # add 全部（.gitignore 已排除 sqlite/.env 等），再核对一次是否有实际变更
    _git(root, "add", "-A")
    if not _has_changes(root):
        return None
    _git(root, "commit", "-m", f"javis {checkpoint_id}")
    commit_hash = _git(root, "rev-parse", "HEAD")

    with _db(root) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, datetime('now'))",
            (checkpoint_id, thread_id, commit_hash),
        )
        conn.commit()
    return commit_hash


def get_commit(root: Path, checkpoint_id: str) -> Optional[str]:
    """查映射表，返回 checkpoint 对应的 commit_hash。"""
    with _db(root) as conn:
        row = conn.execute(
            "SELECT commit_hash FROM snapshots WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
        return row[0] if row else None


def list_snapshots(root: Path) -> list[tuple[str, str, str, str]]:
    """列出全部快照 (checkpoint_id, thread_id, commit_hash, ts)，从旧到新。"""
    with _db(root) as conn:
        return conn.execute(
            "SELECT checkpoint_id, thread_id, commit_hash, ts FROM snapshots "
            "ORDER BY ts ASC"
        ).fetchall()


def delete_snapshots_for_thread(root: Path, thread_id: str) -> int:
    """删除某会话在映射表中的文件快照记录（不改动 git 历史）。"""
    with _db(root) as conn:
        cur = conn.execute("DELETE FROM snapshots WHERE thread_id = ?", (thread_id,))
        conn.commit()
        return cur.rowcount


def resolve_commit(root: Path, raw: str) -> Optional[str]:
    """把用户输入（完整 checkpoint_id 或短 id 前缀）解析成 commit_hash。

    短 id = checkpoint_id 前缀；要求唯一匹配，多个匹配返回 None（歧义）。
    """
    with _db(root) as conn:
        exact = conn.execute(
            "SELECT commit_hash FROM snapshots WHERE checkpoint_id = ?", (raw,)
        ).fetchone()
        if exact:
            return exact[0]
        rows = conn.execute(
            "SELECT checkpoint_id, commit_hash FROM snapshots WHERE checkpoint_id LIKE ?",
            (raw + "%",),
        ).fetchall()
        if len(rows) == 1:
            return rows[0][1]
        return None


def rollback(root: Path, checkpoint_id: str) -> Optional[str]:
    """按 checkpoint_id 回退项目文件到对应 commit，返回 commit_hash；找不到返回 None。"""
    root = Path(root).resolve()
    commit = get_commit(root, checkpoint_id)
    if commit is None:
        return None
    return rollback_commit(root, commit)


def rollback_commit(root: Path, commit: str) -> str:
    """按 commit_hash 回退项目文件到该提交，返回 commit_hash。"""
    _git(root, "reset", "--hard", commit)
    return commit