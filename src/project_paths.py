"""项目根与安装目录解析（OpenCode 式：运行目录即 workspace）。"""
from __future__ import annotations

import os
from pathlib import Path

JAVIS_JSON = "javis.json"
ENV_PROJECT_ROOT = "JARVIS_PROJECT_ROOT"


def install_root() -> Path:
    """JARVIS 引擎安装目录（含 src/、内置 skills/）。"""
    return Path(__file__).resolve().parent.parent


def discover_project_root(start: Path | None = None) -> Path:
    """从 start（默认 cwd）向上查找 javis.json；找不到则返回 start/cwd。

    环境变量 JARVIS_PROJECT_ROOT 可强制指定。
    """
    override = os.environ.get(ENV_PROJECT_ROOT, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / JAVIS_JSON).is_file():
            return directory
    return current


_runtime_project_root: Path | None = None


def set_runtime_project_root(root: Path) -> None:
    """启动时由 load_config / main 设置当前会话项目根。"""
    global _runtime_project_root
    _runtime_project_root = Path(root).resolve()


def get_project_root() -> Path:
    """当前会话项目根；未设置时 discover。"""
    if _runtime_project_root is not None:
        return _runtime_project_root
    return discover_project_root()


def resolve_javis_json(project_root: Path | None = None) -> Path:
    """解析 javis.json 路径：项目根优先，否则安装目录。"""
    root = (project_root or discover_project_root()).resolve()
    candidate = root / JAVIS_JSON
    if candidate.is_file():
        return candidate
    install_candidate = install_root() / JAVIS_JSON
    if install_candidate.is_file():
        return install_candidate
    return candidate


def resolve_env_file(project_root: Path | None = None) -> Path:
    """解析 .env：项目根优先，否则安装目录。"""
    root = (project_root or discover_project_root()).resolve()
    for candidate in (root / ".env", install_root() / ".env"):
        if candidate.is_file():
            return candidate
    return root / ".env"
