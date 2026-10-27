"""工单 11：记忆目录全局化对齐（GUI 展示层 + 配置路径一致）。

主线 javis-global-memory（0019eac）已在 rebase 基线上：memory_dir 缺省/哨兵值
"memory"/空 → JARVIS_HOME/memory（默认 ~/.jarvis/memory），GUI 不重复实现迁移
逻辑，只负责「向导文案说明落点 + 自检页可读到同一路径」。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from PySide6.QtWidgets import QLabel

from src.config import load_config
from tests.gui_fakes import TEST_ROOT, cleanup_home, new_home


def _new_home_with_home(monkeypatch) -> tuple[Path, Path]:
    home = new_home()
    jarvis_home = TEST_ROOT / f"jarvis-home-{uuid.uuid4().hex[:10]}"
    jarvis_home.mkdir(parents=True)
    monkeypatch.setenv("JARVIS_HOME", str(jarvis_home))
    return home, jarvis_home


def test_welcome_page_mentions_global_paths(qapp):
    from src.gui.wizard import WelcomePage

    page = WelcomePage()
    text = page.findChild(QLabel).text()
    assert "%APPDATA%\\Jarvis" in text
    assert ".jarvis" in text
    assert "安装目录" in text and "分离" in text
    assert "记忆" in text


def test_config_memory_dir_sentinel_points_to_jarvis_home(monkeypatch):
    home, jarvis_home = _new_home_with_home(monkeypatch)
    try:
        # new_home 的 jarvis.json 不含 memory_dir → 哨兵语义，落全局
        cfg = load_config(project_root=home)
        assert cfg.memory_dir == (jarvis_home / "memory").resolve()
        assert cfg.memory_dir != (home / "memory").resolve()

        # 显式相对路径 = 项目根（项目级信息记忆可显式选择）
        (home / "jarvis.json").write_text(
            json.dumps({"memory_dir": "project-memory"}), encoding="utf-8"
        )
        cfg2 = load_config(project_root=home)
        assert cfg2.memory_dir == (home / "project-memory").resolve()

        # 显式绝对路径原样
        abs_dir = jarvis_home / "custom-mem"
        (home / "jarvis.json").write_text(
            json.dumps({"memory_dir": str(abs_dir)}), encoding="utf-8"
        )
        assert load_config(project_root=home).memory_dir == abs_dir.resolve()
    finally:
        cleanup_home(home)


def test_dream_paths_follow_config_memory_dir():
    """梦境沉淀/知识库路径由 config.memory_dir 派生（全局化后自动跟随）。"""
    from src import dream

    root = TEST_ROOT / f"dream-{uuid.uuid4().hex[:10]}"
    mem = root / "memory"
    try:
        class _Cfg:
            memory_dir = mem

        assert dream.knowledge_dir(_Cfg()) == mem / dream.DREAM_DIR
        assert dream.KNOWLEDGE_NAME == "knowledge.md"
        assert dream.RUN_LOG_NAME == "runs.md"
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)
