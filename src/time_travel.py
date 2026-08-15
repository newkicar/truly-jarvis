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

DB_NAME = "git_mapping.sqlite"

# 不参与快照的目录/文件（快照自身 + 数据库 + 密钥）
_SKIP = {
    ".git",
    "__pycache__",
    DB_NAME,
    "checkpoints.sqlite",
    "checkpoints.sqlite-shm",
    "checkpoints.sqlite-wal",
    ".env",
    ".pytest_cache",
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _has_changes(root: Path) -> bool:
    """项目目录是否有未提交变更。"""
    return bool(_git(root, "status", "--porcelain"))


def _db_path(root: Path) -> Path:
    return root / DB_NAME


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


def list_snapshots(root: Path) -> list[tuple[str, str, str]]:
    """列出全部快照 (checkpoint_id, thread_id, commit_hash)。"""
    with _db(root) as conn:
        return conn.execute(
            "SELECT checkpoint_id, thread_id, commit_hash FROM snapshots "
            "ORDER BY ts DESC"
        ).fetchall()


def rollback(root: Path, checkpoint_id: str) -> Optional[str]:
    """按 checkpoint_id 回退项目文件到对应 commit，返回 commit_hash；找不到返回 None。"""
    root = Path(root).resolve()
    commit = get_commit(root, checkpoint_id)
    if commit is None:
        return None
    _git(root, "reset", "--hard", commit)
    return commit