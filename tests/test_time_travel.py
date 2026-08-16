"""time_travel 模块测试（git 快照 + 映射表）。

Seam: src.time_travel.snapshot / rollback / get_commit / list_snapshots。
在临时 git 仓库里验证：有变更时 snapshot 提交并记录映射，无变更时跳过，
rollback 按 checkpoint_id 回退文件。
"""
import subprocess
from pathlib import Path

from src import time_travel


def _init_git_repo(root: Path):
    root = Path(root)
    if not (root / "file.txt").exists():
        (root / "file.txt").write_text("v1", encoding="utf-8")
    for cmd in [
        ["git", "init", "-q"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"],
    ]:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        assert r.returncode == 0, f"{cmd} failed: {r.stderr}"
    commit = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
        cwd=str(root), capture_output=True, text=True,
    )
    assert commit.returncode == 0, f"commit failed: {commit.stderr!r} {commit.stdout!r}"


def test_snapshot_and_rollback(tmp_path):
    (tmp_path / "file.txt").write_text("v1", encoding="utf-8")
    _init_git_repo(tmp_path)

    # 无变更 -> 不产生快照
    assert time_travel.snapshot(tmp_path, "t1", "c1") is None

    # 有变更 -> 快照并记录映射（此时文件为 v2，c1 对应 v2 状态）
    (tmp_path / "file.txt").write_text("v2", encoding="utf-8")
    commit = time_travel.snapshot(tmp_path, "t1", "c1")
    assert commit is not None
    assert time_travel.get_commit(tmp_path, "c1") == commit

    # 再改一次，回退到 c1 应恢复 v2（c1 快照时的文件状态）
    (tmp_path / "file.txt").write_text("v3", encoding="utf-8")
    assert time_travel.rollback(tmp_path, "c1") == commit
    assert (tmp_path / "file.txt").read_text(encoding="utf-8") == "v2"


def test_rollback_unknown_checkpoint_returns_none(tmp_path):
    _init_git_repo(tmp_path)
    assert time_travel.rollback(tmp_path, "nonexistent") is None


def test_list_snapshots(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    time_travel.snapshot(tmp_path, "t9", "c9")
    rows = time_travel.list_snapshots(tmp_path)
    assert any(cid == "c9" and tid == "t9" for cid, tid, _, _ in rows)


def test_list_snapshots_orders_oldest_first(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    time_travel.snapshot(tmp_path, "t1", "c1")
    time_travel.snapshot(tmp_path, "t2", "c2")
    rows = time_travel.list_snapshots(tmp_path)
    assert [r[0] for r in rows] == ["c1", "c2"]


def test_resolve_commit_supports_short_prefix(tmp_path):
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    commit1 = time_travel.snapshot(tmp_path, "t1", "c1-1111-2222-3333")
    (tmp_path / "a.txt").write_text("y", encoding="utf-8")
    time_travel.snapshot(tmp_path, "t2", "c1-aaaa-bbbb-cccc")

    assert time_travel.resolve_commit(tmp_path, "c1-1111-2222-3333") == commit1
    assert time_travel.resolve_commit(tmp_path, "c1-1111-2222-33") == commit1  # 短前缀
    assert time_travel.resolve_commit(tmp_path, "c1-") is None  # 歧义（两个 c1- 开头）
    assert time_travel.resolve_commit(tmp_path, "zzz") is None  # 未找到