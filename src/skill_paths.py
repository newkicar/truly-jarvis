"""Skill 目录发现：安装包 + 用户全局 ~/.jarvis + 项目。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config import Config
from src.project_paths import install_root, user_home

BUILTIN_SKILLS_VPATH = "/builtin-skills/"
USER_SKILLS_VPATH = "/skills/"


@dataclass(frozen=True)
class SkillLayer:
    virtual_path: str
    fs_path: Path


def discover_skill_layers(config: Config) -> tuple[SkillLayer, ...]:
    """返回 skill 层（低→高优先级）。同名 skill 时后层覆盖前层。"""
    layers: list[SkillLayer] = []

    install_skills = install_root() / "skills"
    if install_skills.is_dir():
        layers.append(SkillLayer(BUILTIN_SKILLS_VPATH, install_skills.resolve()))

    user_skills = user_home() / "skills"
    user_skills.mkdir(parents=True, exist_ok=True)
    layers.append(SkillLayer(USER_SKILLS_VPATH, user_skills.resolve()))

    root = config.project_root
    seen: set[Path] = set()
    for raw in config.skills:
        fs_path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
        if not fs_path.is_dir() or fs_path in seen:
            continue
        seen.add(fs_path)
        try:
            rel = fs_path.relative_to(root).as_posix().strip("/")
        except ValueError:
            continue
        vpath = f"/workspace/{rel}/" if rel else "/workspace/"
        layers.append(SkillLayer(vpath, fs_path))

    return tuple(layers)


def skill_virtual_sources(config: Config) -> list[str]:
    """deepagents skills= 虚拟路径列表。"""
    return list(dict.fromkeys(layer.virtual_path for layer in discover_skill_layers(config)))


def skill_backend_routes(config: Config) -> dict[str, Path]:
    """除 /workspace/ 外需单独挂 FilesystemBackend 的 skill 层。"""
    routes: dict[str, Path] = {}
    for layer in discover_skill_layers(config):
        if layer.virtual_path.startswith("/workspace/"):
            continue
        routes[layer.virtual_path] = layer.fs_path
    return routes
