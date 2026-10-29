"""GUI 自配层 → 内核 Config 的 env_overrides 通道（无项目 .env 也能启动 GUI）。

工单 12/13 之后，基础客户端不要求项目 .env：向导存的 LLM 凭据经
load_config(env_overrides=...) 喂内核；.env 缺失从 FileNotFoundError 降级为
「必需键缺失才 KeyError」。
"""
from __future__ import annotations

import json

import pytest

from src.config import load_config
from tests.gui_fakes import TEST_ROOT, cleanup_home, new_home


def test_overrides_fill_required_keys_without_env_file():
    home = new_home()
    try:
        (home / ".env").unlink()
        cfg = load_config(
            project_root=home,
            env_overrides={"base_url": "https://gw/v1", "API_KEY": "sk-x",
                           "MODEL_ID": "m", "TAVILY_KEY": ""},
        )
        assert cfg.base_url == "https://gw/v1"
        assert cfg.api_key == "sk-x"
        assert cfg.model_id == "m"
        assert cfg.tavily_key == ""
    finally:
        cleanup_home(home)


def test_missing_keys_raise_keyerror_not_fileerror():
    """无 .env 且无 overrides：KeyError（可行动提示），不再是 FileNotFoundError。"""
    home = new_home()
    try:
        (home / ".env").unlink()
        with pytest.raises(KeyError):
            load_config(project_root=home)
    finally:
        cleanup_home(home)


def test_overrides_take_precedence_over_env_file():
    """overrides > .env（GUI 自配层优先于项目文件）。"""
    home = new_home()
    try:
        cfg = load_config(project_root=home, env_overrides={"BASE_URL": "https://ovr/v1"})
        assert cfg.base_url == "https://ovr/v1"
    finally:
        cleanup_home(home)


def test_no_env_file_at_all_still_loads_with_full_overrides():
    """全新项目（auto_init 只生成 jarvis.json，不生成 .env）+ 全量 overrides。"""
    import uuid
    from pathlib import Path

    home = TEST_ROOT / f"noenv-{uuid.uuid4().hex[:10]}"
    home.mkdir(parents=True)
    try:
        (home / "jarvis.json").write_text(json.dumps({}), encoding="utf-8")
        cfg = load_config(
            project_root=home,
            env_overrides={"BASE_URL": "u", "API_KEY": "k", "MODEL_ID": "m", "TAVILY_KEY": ""},
        )
        assert cfg.model_id == "m"
        assert cfg.checkpoint_db.is_relative_to(home)
    finally:
        cleanup_home(home)
