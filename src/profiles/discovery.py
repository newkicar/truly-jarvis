"""Headless 公开发现面（ADR-0012 同款懒导出风格）。

外部项目（如 local_dots）按 adapter 纪律只 import 公开 jarvis 包、
不 import src 内部模块；本模块即 Agent Profile Registry 的公开
只读投影：三层发现（builtin -> user -> project），结构化返回，
无副作用（get() 不写 db，只有 load() 才写）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _clean_path(value: Path | str | None) -> Path | None:
    """None / 空串 / 纯空白串 一律视为未提供（返回 None）。

    防止 str 输入退化为 Path("") == Path(".")（相对当前 cwd 的错误层目录）；
    Path 对象原样保留。
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return Path(value) if value else None
    return value


@dataclass(frozen=True)
class ProfileInfo:
    """Agent Profile 的结构化只读投影。"""

    profile_id: str
    version: int | None    # None = legacy
    is_legacy: bool
    layer: str             # "builtin" | "user" | "project" | "legacy"
    role: str | None       # identity.role（空 -> None）
    description: str
    engine: str | None     # runtime.engine（空 -> None）


def list_profiles(
    *,
    user_home: Path | str | None = None,
    workspace: Path | str | None = None,
) -> list[ProfileInfo]:
    """三层发现（builtin->user->project），结构化返回，只读。

    user_home 缺省 ~/.jarvis（尊重 JARVIS_HOME）；空串/纯空白入参等同 None；
    workspace 缺省（或空串）则不含 project 层。
    解析失败的 pid 直接传播 ProfileError（保持 Registry.get 失败语义）。
    """
    from .registry import ProfileRegistry

    reg = ProfileRegistry(
        user_home=_clean_path(user_home),
        workspace=_clean_path(workspace),
    )
    infos: list[ProfileInfo] = []
    for pid in reg.list():
        p = reg.get(pid)
        infos.append(
            ProfileInfo(
                profile_id=pid,
                version=None if p.is_legacy else p.profile_version,
                is_legacy=p.is_legacy,
                layer=reg.layer_of(pid),
                role=p.identity.role or None,
                description=(p.description or "").strip(),
                engine=p.runtime.engine or None,
            )
        )
    return infos
