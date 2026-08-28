from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolCallView:
    name: str
    id: str
    args: dict = field(default_factory=dict)

    def arg_value(self, *keys: str) -> str:
        return arg_value(self.args, *keys)

    def command(self) -> str:
        return command(self.args)


def arg_value(args: dict, *keys: str) -> str:
    if not isinstance(args, dict):
        return ""
    for k in keys:
        v = args.get(k)
        if v is not None:
            return str(v)
    return ""


def command(args: dict) -> str:
    raw = (args or {}).get("command") or (args or {}).get("cmd") or ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)):
        return " ".join(str(c) for c in raw)
    return str(raw)


def tool_call_view(request) -> ToolCallView:
    tool_call = getattr(request, "tool_call", None) or {}
    if isinstance(tool_call, dict):
        name = str(tool_call.get("name", "") or "")
        tid = str(tool_call.get("id", "") or "")
        args = tool_call.get("args", {}) or {}
    else:
        name = ""
        tid = ""
        args = {}
    if not isinstance(args, dict):
        args = {}
    return ToolCallView(name=name, id=tid, args=args)


__all__ = ["ToolCallView", "arg_value", "command", "tool_call_view"]
