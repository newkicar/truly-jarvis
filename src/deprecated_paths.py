"""拦截对已废弃路径（如 system-context）的工具访问。"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware

from src.permissions import _command_from_args, _tool_arg_value

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


class DeprecatedPathMiddleware(AgentMiddleware):
    """阻止模型访问已删除的 system-context skill 路径。"""

    @property
    def name(self) -> str:
        return "deprecated-path-guard"

    def _blocked(self, request) -> tuple[str, str] | None:
        tool_call = getattr(request, "tool_call", None) or {}
        if not isinstance(tool_call, dict):
            return None
        tool = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        if tool in _PATH_TOOLS:
            path = _tool_arg_value(args, "file_path", "path")
            pattern = _tool_arg_value(args, "pattern", "glob_pattern")
            if references_deprecated_path(path, pattern):
                return tool, path or pattern
        if tool == "execute":
            cmd = _command_from_args(args)
            if references_deprecated_path(cmd):
                return tool, cmd[:120]
        return None

    def wrap_tool_call(self, request, handler):
        blocked = self._blocked(request)
        if blocked:
            from langchain_core.messages import ToolMessage

            tool, detail = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=deprecated_path_message(tool, detail),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._blocked(request)
        if blocked:
            from langchain_core.messages import ToolMessage

            tool, detail = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=deprecated_path_message(tool, detail),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return await handler(request)
