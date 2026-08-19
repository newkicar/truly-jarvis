"""审批权限配置（对标 opencode permission）。

javis.json 的 "permissions" 段控制哪些工具调用需要人工审批：
  - "allow"        自动放行（等价 opencode "allow"）
  - "ask"          每次调用都请求审批（等价 opencode "ask"，默认）
  - "deny"         直接拒绝（等价 opencode "deny"）
  - 对象形态：{ "<模式>": "<动作>", ... } 按规则集匹配（最后匹配胜出），
    用于按命令前缀/路径模式做精细控制（如 {"*": "ask", "git *": "allow"}）。

关键设计：_build_interrupt_on 返回 (interrupt_on, state)。state 是可变 dict，
运行时「always approve」只改 state 并写回 javis.json，when 谓词闭包引用它，
下次调用自动生效，无需重建 agent。
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from langchain.agents.middleware.types import AgentMiddleware

# 需要审批的工具（deepagents 默认 gated tools）；read/glob/grep 只读工具不审批。
GATED_TOOLS = ("execute", "write_file", "edit_file", "delete")

VALID_ACTIONS = ("allow", "ask", "deny")


def _match_pattern(pattern: str, value: str) -> bool:
    """通配匹配：* 任意多字符，? 单字符；用 fnmatch 实现（opencode 同语义）。"""
    return fnmatch.fnmatch(value, pattern)


def resolve_tool_action(rule: object, value: str) -> str:
    """按规则集解析一次具体调用应走的动作（allow/ask/deny）。

    rule 形态：
      - 字符串：直接作为动作。
      - dict：{模式: 动作}，按插入序匹配 value，最后匹配者胜（opencode 语义）。
      未匹配到任何模式时返回默认 "ask"（用户要求「不配置即审批」）。
    """
    if isinstance(rule, str):
        return rule if rule in VALID_ACTIONS else "ask"
    if isinstance(rule, dict):
        action = "ask"
        for pattern, act in rule.items():
            if isinstance(act, str) and act in VALID_ACTIONS and _match_pattern(pattern, value):
                action = act
        return action
    return "ask"


def _tool_arg_value(args: dict, *keys: str) -> str:
    """从工具调用 args 里取指定字段（多个候选键取第一个存在的）。"""
    if not isinstance(args, dict):
        return ""
    for k in keys:
        v = args.get(k)
        if v is not None:
            return str(v)
    return ""


def _command_from_args(args: dict) -> str:
    """从 execute 工具参数里还原命令字符串（shell 命令或 command 列表）。"""
    raw = args.get("command") or args.get("cmd") or ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)):
        return " ".join(str(c) for c in raw)
    return str(raw)


def _action_from_tool_call(state: dict, tool: str, request) -> str:
    """按 state 当前规则 + 一次工具调用参数解析动作（allow/ask/deny）。

    request 是 ToolCallRequest（含 .tool_call dict）或直接 ToolCall dict。
    """
    tool_call = getattr(request, "tool_call", None)
    if isinstance(tool_call, dict) and "name" in tool_call:
        tool = tool_call.get("name", tool)
        args = tool_call.get("args", {})
    else:
        args = getattr(request, "args", None) or {}
    active_rule = state["tools"].get(tool, state["default"])
    if isinstance(active_rule, str):
        return active_rule if active_rule in VALID_ACTIONS else "ask"
    if tool == "execute":
        value = _command_from_args(args)
    else:
        value = _tool_arg_value(args, "file_path", "path", "pattern", "command")
    return resolve_tool_action(active_rule, value)


def _build_when(state: dict, tool: str, rule: object):
    """构造 when 谓词：按 state 里该工具的当前规则 + 调用参数决定是否中断。

    只有 action=="ask" 才中断（返回 True）；allow/deny 不中断（deny 由
    PermissionDenyMiddleware 在工具层拦截）。
    """
    def when(request) -> bool:
        return _action_from_tool_call(state, tool, request) == "ask"
    return when


def build_permission_interrupts(permissions: dict | None) -> tuple[dict, dict]:
    """把 javis.json 的 permissions 配置转成 deepagents 的 interrupt_on。

    返回 (interrupt_on, state)：
      - interrupt_on：传给 create_deep_agent 的 dict。
      - state：{"tools": {tool: rule}, "default": rule} 可变引用，运行时改它即改行为。

    permissions 缺省/为 None 时，所有 gated tool 默认 "ask"（每次都审批）。
    """
    permissions = permissions or {}
    default = permissions.get("*", "ask")
    state = {
        "default": default,
        "tools": {t: permissions.get(t, default) for t in GATED_TOOLS},
    }
    return _build_interrupt_on(state), state


def build_permission_interrupts_from_state(state: dict) -> dict:
    """从已构造的 state 重建 interrupt_on（供外部复用同一 state 引用时使用）。"""
    return _build_interrupt_on(state)


def _build_interrupt_on(state: dict) -> dict:
    interrupt_on: dict = {}
    for tool in GATED_TOOLS:
        rule = state["tools"][tool]
        if isinstance(rule, str) and rule == "allow":
            interrupt_on[tool] = False  # 自动放行
        elif isinstance(rule, str) and rule == "deny":
            interrupt_on[tool] = False  # deny 由工具层拦截；这里不中断
        else:
            decisions = (
                ["approve", "reject", "edit"]
                if tool in ("write_file", "edit_file")
                else ["approve", "reject"]
            )
            interrupt_on[tool] = {
                "allowed_decisions": decisions,
                "description": f"审批：{tool} 工具调用",
                "when": _build_when(state, tool, rule),
            }
    return interrupt_on


def build_permission_deny_middleware(state: dict) -> PermissionDenyMiddleware:
    """构造 deny 拦截 middleware（与 interrupt_on 共享同一 state 引用）。"""
    return PermissionDenyMiddleware(state)


def apply_permission_override(state: dict, tool: str, action: str, value: str = "*") -> None:
    """运行时把某工具设为 allow/ask/deny（always approve 入口）。

    若该工具当前是规则集形态，则追加/更新一条全匹配规则；否则直接置字符串。
    """
    rule = state["tools"].get(tool, state["default"])
    if isinstance(rule, dict):
        rule[value] = action
    else:
        state["tools"][tool] = action


class PermissionDenyMiddleware(AgentMiddleware):
    """deny 规则拦截：命中 deny 的工具调用不执行，直接返回 permission-denied 错误。

    挂在 wrap_tool_call / awrap_tool_call（工具执行前），state 与 interrupt_on
    共享同一引用 —— always approve / 运行时改 state 立即生效，无需重建 agent。
    返回错误 ToolMessage 而非中断（无人工审批），覆盖 CLI / 定时任务 / invoke。
    """

    def __init__(self, state: dict):
        super().__init__()
        self.state = state

    @property
    def name(self) -> str:
        return "permission-deny"

    def _deny(self, request, tool: str) -> str:
        """命中 deny 时生成给模型的错误消息。"""
        tool_call = getattr(request, "tool_call", None) or {}
        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
        value = _command_from_args(args) if tool == "execute" else _tool_arg_value(
            args, "file_path", "path", "pattern", "command"
        )
        return (
            f"Permission denied: 操作被 javis.json permissions 规则拒绝（deny）。"
            f"工具 {tool}，参数 {value or args}。请更换方案或询问用户，不要重试相同调用。"
        )

    def wrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or {}
        tool = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        if tool in GATED_TOOLS and _action_from_tool_call(self.state, tool, request) == "deny":
            from langchain_core.messages import ToolMessage

            return ToolMessage(
                content=self._deny(request, tool),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, "tool_call", None) or {}
        tool = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        if tool in GATED_TOOLS and _action_from_tool_call(self.state, tool, request) == "deny":
            from langchain_core.messages import ToolMessage

            return ToolMessage(
                content=self._deny(request, tool),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return await handler(request)


def dump_permissions_json(permissions: dict, json_path: Path) -> None:
    """把当前内存 permissions 写回 javis.json（供 always approve 持久化）。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["permissions"] = permissions
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )