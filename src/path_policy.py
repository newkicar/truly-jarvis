"""#10 路径放开：deepagents middleware 层的 Windows 盘符路径定点适配。

背景（2026-08-25 调研）：workspace backend 已以 virtual_mode=False 构造，但
FilesystemMiddleware 的工具包装层无条件调用 validate_path，它拒绝一切盘符
路径（^[a-zA-Z]:）——与 backend 的 virtual_mode 无关。效果：

- `/dir/file` 形式 → 落到项目所在盘根的任意目录（同盘自由），天然可用；
- 相对路径 → 以项目根为基准；
- 盘符路径（跨盘符访问）→ 被 middleware 拒绝 ← 本模块解锁的唯一缺口。

做法：替换 deepagents.middleware.filesystem 命名空间里的 validate_path 引用，
盘符路径原样放行、其余走原实现。backend 侧 virtual_mode=False 本就支持
Windows 绝对路径。这是对 deepagents 0.7.6 的定点适配——升级 deepagents 时
需复核 middleware 的 import 方式与校验逻辑是否变化。
"""
from __future__ import annotations

import re

from deepagents.backends import utils as _backends_utils

_DRIVE_LETTER_RE = re.compile(r"^[a-zA-Z]:")

_original_validate_path = _backends_utils.validate_path


def _unrestricted_validate_path(path: str, *, allowed_prefixes=None) -> str:
    """盘符路径原样放行；其余保持 deepagents 原校验语义（含 traversal 拦截）。"""
    if isinstance(path, str) and _DRIVE_LETTER_RE.match(path):
        return path
    return _original_validate_path(path, allowed_prefixes=allowed_prefixes)


def apply_unrestricted_paths() -> None:
    """把放行版 validate_path 接入 FilesystemMiddleware（幂等）。"""
    from deepagents.middleware import filesystem as _fs_middleware

    if getattr(_fs_middleware.validate_path, "__name__", "") != "_unrestricted_validate_path":
        _fs_middleware.validate_path = _unrestricted_validate_path


def validate_path(path: str, *, allowed_prefixes=None) -> str:
    return _unrestricted_validate_path(path, allowed_prefixes=allowed_prefixes)


apply_unrestricted_paths()

__all__ = ["apply_unrestricted_paths", "validate_path"]
