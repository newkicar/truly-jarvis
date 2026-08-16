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
import re
from pathlib import Path

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


def _build_when(state: dict, tool: str, rule: object):
    """构造 when 谓词：按 state 里该工具的当前规则 + 调用参数决定是否中断。

    只有 action=="ask" 才中断（返回 True）；allow/deny 都放行（deny 在工具层拦截）。
    """
    def when(request) -> bool:
        active_rule = state["tools"].get(tool, state["default"])
        if isinstance(active_rule, str):
            action = active_rule
        else:
            tool_call = getattr(request, "tool_call", None) or {}
            args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
            if tool == "execute":
                value = _command_from_args(args)
            else:
                value = _tool_arg_value(args, "file_path", "path", "pattern", "command")
            action = resolve_tool_action(active_rule, value)
        return action == "ask"
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

    interrupt_on: dict = {}
    for tool in GATED_TOOLS:
        rule = state["tools"][tool]
        if isinstance(rule, str) and rule == "allow":
            interrupt_on[tool] = False  # 自动放行
        elif isinstance(rule, str) and rule == "deny":
            interrupt_on[tool] = False  # deny 由文件系统权限拦截；这里不中断
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
    return interrupt_on, state


def apply_permission_override(state: dict, tool: str, action: str, value: str = "*") -> None:
    """运行时把某工具设为 allow/ask/deny（always approve 入口）。

    若该工具当前是规则集形态，则追加/更新一条全匹配规则；否则直接置字符串。
    """
    rule = state["tools"].get(tool, state["default"])
    if isinstance(rule, dict):
        rule[value] = action
    else:
        state["tools"][tool] = action


def dump_permissions_json(permissions: dict, json_path: Path) -> None:
    """把当前内存 permissions 写回 javis.json（供 always approve 持久化）。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["permissions"] = permissions
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )