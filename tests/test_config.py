"""配置层测试。

Seam: src.config 的公开接口 load_config / 各解析函数。
只测外部行为（输入 → 输出 dataclass），不测内部实现。
"""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from src.config import (
    Config,
    ConfigError,
    load_config,
    parse_env_file,
    parse_env_text,
)


def test_parse_env_colon_separated(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://example.com\napi_key:sk-123\n", encoding="utf-8")
    result = parse_env_file(env_file)
    assert result["BASE_URL"] == "https://example.com"
    assert result["API_KEY"] == "sk-123"


def test_parse_env_equals_separated(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("BASE_URL=https://example.com\nAPI_KEY=sk-123\n", encoding="utf-8")
    result = parse_env_file(env_file)
    assert result["BASE_URL"] == "https://example.com"
    assert result["API_KEY"] == "sk-123"


def test_parse_env_key_case_insensitive(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("model_id:deepseek-v4-flash\n", encoding="utf-8")
    result = parse_env_file(env_file)
    assert result["MODEL_ID"] == "deepseek-v4-flash"


def test_parse_env_ignores_comments_and_blank_lines():
    text = "# comment line\n\nbase_url:https://example.com\n"
    result = parse_env_text(text)
    assert result["BASE_URL"] == "https://example.com"
    assert "#" not in [k for k in result]


def test_parse_env_value_with_colons_kept_intact():
    text = "base_url:https://example.com:8080/v1\n"
    result = parse_env_text(text)
    assert result["BASE_URL"] == "https://example.com:8080/v1"


def test_load_config_builds_dataclass(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "base_url:https://opencode.ai/zen/go/v1\n"
        "api_key:sk-test\n"
        "model_id:deepseek-v4-flash\n"
        "tavily_key:tvly-test\n",
        encoding="utf-8",
    )
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {
                    "base_url_env": "BASE_URL",
                    "api_key_env": "API_KEY",
                    "model_id_env": "MODEL_ID",
                },
                "obsidian_vault": str(tmp_path / "vault"),
                "memory_dir": "memory",
                "skills": ["skills/"],
                "mcps": {"servers": {}},
                "schedules": [],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert isinstance(cfg, Config)
    assert cfg.project_root == tmp_path.resolve()
    assert cfg.base_url == "https://opencode.ai/zen/go/v1"
    assert cfg.api_key == "sk-test"
    assert cfg.model_id == "deepseek-v4-flash"
    assert cfg.tavily_key == "tvly-test"


def test_load_config_absolutizes_paths(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    vault_rel = tmp_path / "vault"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(vault_rel),
                "memory_dir": "memory",
                "skills": [],
                "mcps": {"servers": {}},
                "schedules": [],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert Path(cfg.vault_path).is_absolute()


def test_load_config_missing_required_key_raises(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(tmp_path / "vault"),
                "memory_dir": "memory",
                "skills": [],
                "mcps": {"servers": {}},
                "schedules": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(KeyError):
        load_config(env_file=env_file, json_file=json_file)


def test_load_config_parses_mcps_dict(tmp_path: Path):
    """mcps 应按 OpenCode 风格 dict（{"servers": {...}}）解析，而非旧 list。"""
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(tmp_path / "vault"),
                "memory_dir": "memory",
                "skills": [],
                "mcps": {
                    "servers": {
                        "git": {"type": "local", "command": ["uvx", "mcp-server-git"], "enabled": True},
                        "playwright": {"type": "local", "command": ["npx", "@playwright/mcp"], "enabled": False},
                        "api": {"type": "remote", "url": "http://localhost:8000/mcp"},
                    }
                },
                "schedules": [],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    servers = cfg.mcps["servers"]
    assert isinstance(servers, dict)
    assert set(servers.keys()) == {"git", "playwright", "api"}
    assert servers["git"]["command"] == ["uvx", "mcp-server-git"]
    assert servers["api"]["url"] == "http://localhost:8000/mcp"


def test_load_config_mcps_inherits_global_defaults(tmp_path: Path):
    """项目未配置 mcps 键时，从全局 ~/.jarvis/jarvis.json 继承默认值。"""
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(tmp_path / "vault"),
                "memory_dir": "memory",
                "skills": [],
                "schedules": [],
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    # 全局 ~/.jarvis/jarvis.json 提供 mcps 默认值，项目未覆盖时继承
    assert "servers" in cfg.mcps


def test_load_config_rag_from_json(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(tmp_path / "vault"),
                "memory_dir": "memory",
                "rag": {
                    "ollama_base_url": "http://ollama:11434",
                    "embed_model": "custom-embed",
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.rag_ollama_base_url == "http://ollama:11434"
    assert cfg.rag_embed_model == "custom-embed"


def test_load_config_tui_from_json(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "jarvis.json"
    json_file.write_text(
        json.dumps(
            {
                "model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"},
                "obsidian_vault": str(tmp_path / "vault"),
                "tui": {"copy_on_select": True},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.tui.get("copy_on_select") is True


def _write_min_env(tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    return env_file


def _write_json(tmp_path: Path, data: dict) -> Path:
    json_file = tmp_path / "jarvis.json"
    base = {"model": {"base_url_env": "BASE_URL", "api_key_env": "API_KEY", "model_id_env": "MODEL_ID"}}
    base.update(data)
    json_file.write_text(json.dumps(base), encoding="utf-8")
    return json_file


def test_load_config_knowledge_base_preferred_over_legacy(tmp_path: Path):
    """knowledge_base 优先于旧键 obsidian_vault。"""
    env_file = _write_min_env(tmp_path)
    json_file = _write_json(
        tmp_path,
        {
            "obsidian_vault": str(tmp_path / "old-vault"),
            "knowledge_base": str(tmp_path / "new-kb"),
        },
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.vault_path == (tmp_path / "new-kb").resolve()


def test_load_config_knowledge_base_falls_back_to_obsidian_vault(tmp_path: Path):
    """未写 knowledge_base 时回退 obsidian_vault（兼容家里电脑旧配置）。"""
    env_file = _write_min_env(tmp_path)
    json_file = _write_json(tmp_path, {"obsidian_vault": str(tmp_path / "vault")})
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.vault_path == (tmp_path / "vault").resolve()


@pytest.mark.parametrize("raw", ["", None])
def test_load_config_empty_knowledge_base_disables_vault(tmp_path: Path, raw):
    """knowledge_base 留空/为 null → vault_path=None（无 /vault/）。"""
    env_file = _write_min_env(tmp_path)
    json_file = _write_json(
        tmp_path,
        {"obsidian_vault": str(tmp_path / "vault"), "knowledge_base": raw},
    )
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.vault_path is None


def test_load_config_no_kb_keys_vault_optional(tmp_path: Path):
    """两个键都没写也不报错：知识库可选（公司电脑场景）。"""
    env_file = _write_min_env(tmp_path)
    json_file = _write_json(tmp_path, {})
    cfg = load_config(env_file=env_file, json_file=json_file)
    assert cfg.vault_path is None


# ---------------------------------------------------------------------------
# gui15 G1/G2: jarvis.json 项目>全局回落语义 + auto_compaction
# 自建临时目录纪律：本机 pytest tmp_path 基目录被 WinError 5 污染，故不用 tmp_path
# ---------------------------------------------------------------------------


_SEQ = 0


def _fresh_dir() -> Path:
    global _SEQ
    _SEQ += 1
    name = "jarvis_cfg_g1_" + str(os.getpid()) + "_" + str(int(time.time() * 1000)) + "_" + str(_SEQ)
    base = Path(tempfile.gettempdir()) / name
    base.mkdir(parents=True, exist_ok=True)
    return base


def _isolated_home(base: Path):
    """把 JARVIS_HOME 指向自建目录，隔离真实全局配置；返回旧值。"""
    old = os.environ.get("JARVIS_HOME")
    os.environ["JARVIS_HOME"] = str(base / "jh")
    return old


def _restore_home(old):
    if old is None:
        os.environ.pop("JARVIS_HOME", None)
    else:
        os.environ["JARVIS_HOME"] = old


def test_load_config_missing_project_json_falls_back_global():
    """项目 jarvis.json 缺失 → 回落全局+内置默认，不崩（gui15 G1 条目9）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        env_file = _write_min_env(base)
        json_file = base / "jarvis.json"  # 故意不创建
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert isinstance(cfg, Config)
        assert cfg.auto_compaction == 0
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)


def test_load_config_corrupt_project_json_raises_configerror():
    """项目 jarvis.json 损坏 → ConfigError 且带可操作修复指引（gui15 G1 条目9）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        env_file = _write_min_env(base)
        json_file = _write_json(base, {})
        json_file.write_text("{ this is not valid json", encoding="utf-8")
        with pytest.raises(ConfigError) as exc_info:
            load_config(env_file=env_file, json_file=json_file)
        msg = str(exc_info.value)
        assert "解决" in msg
        assert str(json_file) in msg
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)


def test_load_config_non_dict_project_json_raises_configerror():
    """项目 jarvis.json 顶层非对象(dict) → ConfigError（gui15 G1 条目9）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        env_file = _write_min_env(base)
        json_file = _write_json(base, {})
        json_file.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_config(env_file=env_file, json_file=json_file)
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)


def test_load_config_auto_compaction_from_json():
    """auto_compaction 正整数 → 启用（gui15 G2 条目8）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        env_file = _write_min_env(base)
        json_file = _write_json(base, {"auto_compaction": 4000})
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert cfg.auto_compaction == 4000
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)


def test_load_config_auto_compaction_invalid_falls_back_zero():
    """auto_compaction 非整数/负数 → 0（不启用）（gui15 G2 条目8）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        env_file = _write_min_env(base)
        json_file = _write_json(base, {"auto_compaction": "nonsense"})
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert cfg.auto_compaction == 0
        json_file = _write_json(base, {"auto_compaction": -8})
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert cfg.auto_compaction == 0
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)


def test_load_config_project_overrides_global_auto_compaction():
    """项目级 > 全局级：项目未配继承全局，配置了项目胜出（gui15 G1 条目9）。"""
    base = _fresh_dir()
    old = _isolated_home(base)
    try:
        (base / "jh").mkdir(parents=True, exist_ok=True)
        (base / "jh" / "jarvis.json").write_text(json.dumps({"auto_compaction": 999}), encoding="utf-8")
        env_file = _write_min_env(base)
        json_file = _write_json(base, {})
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert cfg.auto_compaction == 999
        json_file = _write_json(base, {"auto_compaction": 4000})
        cfg = load_config(env_file=env_file, json_file=json_file)
        assert cfg.auto_compaction == 4000
    finally:
        _restore_home(old)
        shutil.rmtree(base, ignore_errors=True)
