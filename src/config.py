"""配置加载。

读取 .env（BASE_URL/API_KEY/MODEL_ID/TAVILY_KEY）与 javis.json，产出配置 dataclass。
可变项均来自 javis.json，不写死。

注意：当前 .env 是 ':' 分隔、小写键的非标准格式（python-dotenv 读不了），
因此提供自定义解析：同时支持 'KEY:VALUE' 与 'KEY=VALUE'，键名大小写不敏感。
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from src.project_paths import (
    discover_project_root,
    ensure_user_home,
    install_root,
    resolve_env_file,
    resolve_jarvis_json,
    resolve_user_jarvis_json,
    set_runtime_project_root,
)

REQUIRED_ENV_KEYS = ("BASE_URL", "API_KEY", "MODEL_ID", "TAVILY_KEY")

# 全局默认配置（~/.jarvis/jarvis.json）；仅非路径项，路径项由项目级 jarvis.json 决定
GLOBAL_DEFAULTS: dict = {
    "model": {
        "base_url_env": "BASE_URL",
        "api_key_env": "API_KEY",
        "model_id_env": "MODEL_ID",
    },
    "mcps": {"servers": {}},
    "permissions": {
        "*": "ask",
        "execute": "ask",
        "write_file": "ask",
        "edit_file": "ask",
        "delete": "ask",
    },
    "hooks": {"permission": []},
    "rag": {
        "ollama_base_url": "http://localhost:11434",
        "embed_model": "quentinz/bge-small-zh-v1.5",
    },
    "execution": {"max_steps": 200},
    "tui": {"copy_on_select": True},
}


def _deep_merge(base: dict, override: dict) -> dict:
    """合并两个 dict：override 覆盖 base（同 key），嵌套 dict 递归合并。"""
    merged = dict(base)
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def ensure_utf8_stdout() -> None:
    """Windows 控制台默认 GBK，重配 stdout/stderr 为 UTF-8 以正确输出中文/emoji。"""
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass


@dataclass(frozen=True)
class Config:
    """JARVIS 运行时配置。"""

    project_root: Path
    base_url: str
    api_key: str
    model_id: str
    tavily_key: str
    vault_path: Path | None
    memory_dir: Path
    checkpoint_db: Path
    schedules_dir: Path
    skills: tuple[Path, ...]
    mcps: dict[str, object]
    permissions: dict[str, object]
    hooks: dict[str, object]
    agents: dict[str, object]
    rag_ollama_base_url: str
    rag_embed_model: str
    execution_max_steps: int
    tui: dict[str, object]


def parse_env_text(text: str) -> dict[str, str]:
    """解析 .env 文本，支持 'KEY:VALUE' 与 'KEY=VALUE'，键名统一大写。"""
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        first = min(
            (i for i in (line.find(":"), line.find("=")) if i != -1),
            default=-1,
        )
        if first == -1:
            continue
        key = line[:first].strip().upper()
        value = line[first + 1 :].strip()
        if key:
            result[key] = value
    return result


def parse_env_file(env_file: Path) -> dict[str, str]:
    """从文件读取并解析 .env。"""
    return parse_env_text(env_file.read_text(encoding="utf-8"))


def _load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(
    env_file: Path | None = None,
    json_file: Path | None = None,
    project_root: Path | None = None,
) -> Config:
    """加载 .env + jarvis.json，产出 Config。

    配置合并：~/.jarvis/jarvis.json（全局默认）+ 项目 jarvis.json（覆盖全局）。
    未显式传入路径时：从 cwd 发现 project_root，再解析 jarvis.json / .env。
    """
    root = Path(project_root).resolve() if project_root else discover_project_root()
    if json_file is None:
        json_file = resolve_jarvis_json(root)
        if json_file.is_file():
            root = json_file.parent.resolve()
    else:
        json_file = Path(json_file).resolve()
        root = json_file.parent.resolve()

    if env_file is None:
        env_file = resolve_env_file(root)
    else:
        env_file = Path(env_file).resolve()

    if not env_file.is_file():
        fallback = install_root() / ".env"
        if fallback.is_file():
            env_file = fallback

    env = parse_env_file(env_file)

    missing = [k for k in REQUIRED_ENV_KEYS if k not in env]
    if missing:
        raise KeyError(f"缺少必需配置项（.env）: {', '.join(missing)}")

    data = _load_json_file(json_file)

    # 全局配置合并（项目覆盖全局，同 opencode 语义）
    global_cfg_path = resolve_user_jarvis_json()
    if global_cfg_path.is_file():
        try:
            global_data = _load_json_file(global_cfg_path)
            data = _deep_merge(global_data, data)
        except Exception as exc:
            import logging
            logging.warning("全局配置 %s 解析失败，忽略: %s", global_cfg_path, exc)
    model_cfg = data.get("model", {})

    def _resolve_env_name(cfg_key: str, default: str) -> str:
        return model_cfg.get(cfg_key, default)

    base_url = env[_resolve_env_name("base_url_env", "BASE_URL")]
    api_key = env[_resolve_env_name("api_key_env", "API_KEY")]
    model_id = env[_resolve_env_name("model_id_env", "MODEL_ID")]
    tavily_key = env[_resolve_env_name("tavily_key_env", "TAVILY_KEY")]

    # 知识库（可选）：javis.json `knowledge_base` 优先，兼容旧键 `obsidian_vault`；
    # 空字符串 / null / 两键均缺省 → None（本次会话没有 /vault/）。
    kb_raw = data.get("knowledge_base", data.get("obsidian_vault"))
    vault = Path(os.path.expandvars(str(kb_raw))).resolve() if kb_raw else None
    memory = (root / data.get("memory_dir", "memory")).resolve()
    checkpoint_db = (root / data.get("checkpoint_db", "checkpoints.sqlite")).resolve()
    schedules_dir = (root / data.get("schedules_dir", "schedules")).resolve()
    skills = tuple((root / s).resolve() for s in data.get("skills", []))
    mcps = data.get("mcps", {})
    if not isinstance(mcps, dict):
        mcps = {}

    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        agents = {}

    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}

    rag_cfg = data.get("rag", {})
    if not isinstance(rag_cfg, dict):
        rag_cfg = {}

    execution_cfg = data.get("execution", {})
    if not isinstance(execution_cfg, dict):
        execution_cfg = {}
    try:
        max_steps = int(execution_cfg.get("max_steps", 200))
    except (TypeError, ValueError):
        max_steps = 200
    max_steps = max(10, min(max_steps, 9999))

    tui_cfg = data.get("tui", {})
    if not isinstance(tui_cfg, dict):
        tui_cfg = {}

    cfg = Config(
        project_root=root,
        base_url=base_url,
        api_key=api_key,
        model_id=model_id,
        tavily_key=tavily_key,
        vault_path=vault,
        memory_dir=memory,
        checkpoint_db=checkpoint_db,
        schedules_dir=schedules_dir,
        skills=skills,
        mcps=mcps,
        permissions=data.get("permissions", {}),
        hooks=hooks,
        agents=agents,
        rag_ollama_base_url=str(rag_cfg.get("ollama_base_url", "http://localhost:11434")),
        rag_embed_model=str(rag_cfg.get("embed_model", "quentinz/bge-small-zh-v1.5")),
        execution_max_steps=max_steps,
        tui=tui_cfg,
    )
    ensure_user_home()
    set_runtime_project_root(cfg.project_root)
    return cfg