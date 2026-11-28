"""Goal 命令测试共享 harness：自建临时目录纪律（禁 tmp_path / tempfile.mkdtemp，
本机 pytest 基 temp 目录 WinError5 中毒先例）。

tests/ 下 goal 相关测试统一 `from tests._goal_harness import goal_tmp`。
"""
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

_GOAL_TEST_BASE = Path(__file__).resolve().parent.parent / ".scratch" / "goal-cmd-test-tmp"


@contextmanager
def goal_tmp(name: str):
    """os.makedirs 自建唯一目录（uuid8 后缀防并发撞名），用完 rmtree。"""
    d = _GOAL_TEST_BASE / f"{name}-{uuid.uuid4().hex[:8]}"
    os.makedirs(d, exist_ok=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
