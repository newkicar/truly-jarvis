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

REQUIRED_ENV_KEYS = ("BASE_URL", "API_KEY", "MODEL_ID", "TAVILY_KEY")


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

    base_url: str
    api_key: str
    model_id: str
    tavily_key: str
    vault_path: Path
    memory_dir: Path
    checkpoint_db: Path
    schedules_dir: Path
    skills: tuple[Path, ...]
    mcps: dict[str, object]
    permissions: dict[str, object]
    rag_ollama_base_url: str
    rag_embed_model: str


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


def load_config(env_file: Path | None = None, json_file: Path | None = None) -> Config:
    """加载 .env + javis.json，产出 Config。

    未显式传入路径时，默认取项目根目录下的 .env 与 javis.json。
    """
    root = Path(__file__).resolve().parent.parent
    env_file = env_file or root / ".env"
    json_file = json_file or root / "javis.json"

    env = parse_env_file(env_file)

    missing = [k for k in REQUIRED_ENV_KEYS if k not in env]
    if missing:
        raise KeyError(f"缺少必需配置项（.env）: {', '.join(missing)}")

    data = _load_json_file(json_file)
    model_cfg = data.get("model", {})

    def _resolve_env_name(cfg_key: str, default: str) -> str:
        return model_cfg.get(cfg_key, default)

    base_url = env[_resolve_env_name("base_url_env", "BASE_URL")]
    api_key = env[_resolve_env_name("api_key_env", "API_KEY")]
    model_id = env[_resolve_env_name("model_id_env", "MODEL_ID")]
    tavily_key = env[_resolve_env_name("tavily_key_env", "TAVILY_KEY")]

    vault = Path(os.path.expandvars(data["obsidian_vault"])).resolve()
    memory = (root / data.get("memory_dir", "memory")).resolve()
    checkpoint_db = (root / data.get("checkpoint_db", "checkpoints.sqlite")).resolve()
    schedules_dir = (root / data.get("schedules_dir", "schedules")).resolve()
    skills = tuple((root / s).resolve() for s in data.get("skills", []))
    mcps = data.get("mcps", {})
    if not isinstance(mcps, dict):
        mcps = {}

    rag_cfg = data.get("rag", {})
    if not isinstance(rag_cfg, dict):
        rag_cfg = {}

    return Config(
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
        rag_ollama_base_url=str(rag_cfg.get("ollama_base_url", "http://localhost:11434")),
        rag_embed_model=str(rag_cfg.get("embed_model", "quentinz/bge-small-zh-v1.5")),
    )