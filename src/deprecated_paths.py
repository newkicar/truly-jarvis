"""拦截对已废弃路径（如 system-context）的工具访问。"""
from __future__ import annotations

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView

_DEPRECATED_MARKERS = ("system-context", "read_context.py")
_PATH_TOOLS = frozenset({"ls", "read_file", "glob", "grep", "write_file", "edit_file", "delete"})


def _norm(value: str) -> str:
    return value.replace("\\", "/").casefold()


def references_deprecated_path(*values: str) -> bool:
    joined = " ".join(_norm(v) for v in values if v)
    return any(marker in joined for marker in _DEPRECATED_MARKERS)


def deprecated_path_message(tool: str, detail: str) -> str:
    return (
        "system-context 已废弃，目录不存在。不要 retry 此路径。"
        "问今天日期/星期 → 直接读 system prompt 首行「今天是 …」；"
        "问现在几点 → execute（如 Get-Date）；"
        "问所在城市 → execute（如 curl IP 定位）。"
        f"（拦截 {tool}: {detail}）"
    )


class DeprecatedPathMiddleware(GuardMiddleware):
    """阻止模型访问已删除的 system-context skill 路径。"""

    @property
    def name(self) -> str:
        return "deprecated-path-guard"

    def block(self, view: ToolCallView) -> str | None:
        if view.name in _PATH_TOOLS:
            path = view.arg_value("file_path", "path")
            pattern = view.arg_value("pattern", "glob_pattern")
            if references_deprecated_path(path, pattern):
                return deprecated_path_message(view.name, path or pattern)
        if view.name == "execute":
            cmd = view.command()
            if references_deprecated_path(cmd):
                return deprecated_path_message(view.name, cmd[:120])
        return None
