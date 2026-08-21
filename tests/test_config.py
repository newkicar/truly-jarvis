"""配置层测试。

Seam: src.config 的公开接口 load_config / 各解析函数。
只测外部行为（输入 → 输出 dataclass），不测内部实现。
"""
import json
from pathlib import Path

import pytest

from src.config import (
    Config,
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
    json_file = tmp_path / "javis.json"
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
    json_file = tmp_path / "javis.json"
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
    json_file = tmp_path / "javis.json"
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
    json_file = tmp_path / "javis.json"
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


def test_load_config_mcps_missing_defaults_to_empty(tmp_path: Path):
    """未配置 mcps 键时 cfg.mcps 默认为空 dict（向后兼容旧 list 格式）。"""
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "javis.json"
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
    assert cfg.mcps == {}


def test_load_config_rag_from_json(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("base_url:https://x.com\napi_key:k\nmodel_id:m\ntavily_key:t\n", encoding="utf-8")
    json_file = tmp_path / "javis.json"
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
    json_file = tmp_path / "javis.json"
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
