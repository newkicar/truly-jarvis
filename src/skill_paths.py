"""Skill 目录发现：用户全局 ~/.jarvis + 项目（两层模型，对齐 opencode）。"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from src.config import Config
from src.project_paths import install_root, user_home

USER_SKILLS_VPATH = "/skills/"


@dataclass(frozen=True)
class SkillLayer:
    virtual_path: str
    fs_path: Path


def _copy_if_missing(src: str, dst: str) -> None:
    """仅当目标文件不存在时才拷贝（保留用户已编辑的 skill 内容）。"""
    if not Path(dst).exists():
        shutil.copy2(src, dst)


def seed_builtin_skills() -> None:
    """将安装包内置 skill 拷贝到 ~/.jarvis/skills（非破坏性合并：缺失才补，绝不覆盖同名文件）。

    2026-10-25 修复：旧实现 shutil.copytree(dirs_exist_ok=True) 语义为"源覆盖目标"，
    每次启动 ensure_user_home 都会把用户编辑过的同名 SKILL.md 刷回内置版；
    现用 copy_function=_copy_if_missing 改为缺才补。
    """
    builtin_skills = install_root() / "skills"
    user_skills = user_home() / "skills"
    user_skills.mkdir(parents=True, exist_ok=True)

    if builtin_skills.is_dir():
        for child in builtin_skills.iterdir():
            if child.is_dir() and not child.name.startswith(".") and not child.name.startswith("__"):
                target = user_skills / child.name
                shutil.copytree(child, target, dirs_exist_ok=True, copy_function=_copy_if_missing)


def discover_skill_layers(config: Config) -> tuple[SkillLayer, ...]:
    """返回 skill 层（低→高优先级）。两层：全局 USER + 项目 PROJECT。同名 skill 时后层覆盖前层。"""
    layers: list[SkillLayer] = []

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
    """所有 skill 层都单独挂 virtual_mode=True FilesystemBackend（含 /workspace/ 前缀的项目层）。

    项目 skill 层不能靠 unrestricted 的 workspace 默认后端（virtual_mode=False）：
    它返回真实绝对路径，CompositeBackend 对 ls 结果重新前缀化（route_prefix 直接
    拼接 entry_path、丢分隔符）会产出 workspace 后接绝对盘符路径的坏路径，使
    deepagents 的 skill 发现 download 失败（OSError EINVAL）并中断整轮。故项目层
    也用独立虚拟后端挂到自身路由键下（前缀长度倒序，/workspace/skills/ 优先于 /workspace/）。
    """
    routes: dict[str, Path] = {}
    for layer in discover_skill_layers(config):
        routes[layer.virtual_path] = layer.fs_path
    return routes