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
import shlex
from pathlib import Path

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView, arg_value, command, tool_call_view

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


# Shell 包装命令：首 token → 识别旗标。经这些包装执行时，真正的前缀要在两级之后
# （"powershell -Command git ..." → git），否则前缀规则记不到真实命令。
SHELL_WRAPPER_PREFIXES = {
    "cmd": ("/c",),
    "powershell": ("-command", "-c"),
    "pwsh": ("-command", "-c"),
    "bash": ("-c",),
    "sh": ("-c",),
    "wsl": ("-e",),
}


def extract_command_prefix(cmd: str) -> str:
    """提取可审批的命令前缀：首 token（小写）；shell 包装两级剥离。

    提取不到（空/引号错配）返回 "*"（调用方回落整工具放行）。
    """
    if not isinstance(cmd, str) or not cmd.strip():
        return "*"
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.strip().split()
    if not tokens:
        return "*"
    head = tokens[0].lower()
    flags = SHELL_WRAPPER_PREFIXES.get(head)
    rest = tokens[1:]
    if flags and rest and rest[0].lower() in flags:
        inner = rest[1:]
        if inner and inner[0].strip():
            return inner[0].strip().split()[0].lower()
        return "*"
    return head


# 只读启发式表（工单 05）：permissions.heuristics 开启时，命中这些命令 → 自动放行。
# 小写元组；含空格的条目按前两 token 匹配（git status），否则按首 token。
HEURISTIC_SAFE_COMMANDS = (
    "get-date", "whoami", "hostname", "get-location", "pwd",
    "ls", "dir", "get-childitem", "get-content",
    "git status", "git log", "git diff",
    "get-process", "tasklist", "echo",
)


def heuristic_safe(cmd: str) -> bool:
    """命令是否命中只读启发式表（大小写不敏感，前 1–2 token）。"""
    if not isinstance(cmd, str):
        return False
    toks = cmd.lower().split()
    if not toks:
        return False
    one, two = toks[0], " ".join(toks[:2])
    return any(one == item if " " not in item else two == item for item in HEURISTIC_SAFE_COMMANDS)


def _action_for_args(state: dict, tool: str, args: dict) -> str:
    """按 state 当前规则 + 一次工具调用的 args 解析动作（allow/ask/deny）。

    Hook 优先于 javis.json permissions（Codex: Hooks → rules → User）。
    """
    hook_rules = state.get("hooks") or []
    if hook_rules and tool in GATED_TOOLS:
        from src.permission_hooks import resolve_permission_hook

        hook = resolve_permission_hook(
            hook_rules,
            tool,
            args if isinstance(args, dict) else {},
            thread_id=str(state.get("thread_id") or ""),
            project_root=state.get("project_root"),
        )
        if hook is not None:
            decision, _msg = hook
            if decision in VALID_ACTIONS:
                return decision

    if tool == "execute":
        value = command(args)
    else:
        value = arg_value(args, "file_path", "path", "pattern", "command")
    active_rule = state["tools"].get(tool, state["default"])
    if isinstance(active_rule, str):
        action = active_rule if active_rule in VALID_ACTIONS else "ask"
    else:
        action = resolve_tool_action(active_rule, value)
    # 只读启发式（工单 05）：permissions.heuristics 开启时，只读命令免逐次审批
    if (
        action == "ask"
        and tool == "execute"
        and state.get("heuristics")
        and heuristic_safe(value)
    ):
        return "allow"
    return action


def _extract_args_from_request(request) -> dict:
    """从 ToolCallRequest（或兼容对象）提取 args dict。"""
    tool_call = getattr(request, "tool_call", None)
    if isinstance(tool_call, dict) and "name" in tool_call:
        return tool_call.get("args", {}) or {}
    return getattr(request, "args", None) or {}


def _build_when(state: dict, tool: str, rule: object):
    """构造 when 谓词：按 state 里该工具的当前规则 + 调用参数决定是否中断。

    只有 action=="ask" 才中断（返回 True）；allow/deny 不中断（deny 由
    PermissionDenyMiddleware 在工具层拦截）。
    """
    def when(request) -> bool:
        args = _extract_args_from_request(request)
        return _action_for_args(state, tool, args) == "ask"
    return when


def sync_permission_context(
    state: dict | None,
    *,
    thread_id: str = "",
    project_root: Path | None = None,
) -> None:
    """每轮对话前写入 thread_id / project_root，供 permission hooks 使用。"""
    if state is None:
        return
    state["thread_id"] = thread_id
    if project_root is not None:
        state["project_root"] = project_root


def build_permission_interrupts(
    permissions: dict | None,
    *,
    hooks: dict | None = None,
    project_root: Path | None = None,
) -> tuple[dict, dict]:
    """把 javis.json 的 permissions 配置转成 deepagents 的 interrupt_on。

    返回 (interrupt_on, state)：
      - interrupt_on：传给 create_deep_agent 的 dict。
      - state：{"tools": {tool: rule}, "default": rule} 可变引用，运行时改它即改行为。

    permissions 缺省/为 None 时，所有 gated tool 默认 "ask"（每次都审批）。
    """
    from src.permission_hooks import parse_permission_hooks

    permissions = permissions or {}
    default = permissions.get("*", "ask")
    hook_rules = parse_permission_hooks(hooks or {}, project_root=project_root)
    state = {
        "default": default,
        "tools": {t: permissions.get(t, default) for t in GATED_TOOLS},
        "hooks": hook_rules,
        "thread_id": "",
        "project_root": project_root,
        "heuristics": bool(permissions.get("heuristics", False)),
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
            # 全部 gated 工具开放 "edit" 决策：UI/CLI 已对所有工具提供「编辑参数」入口
            # （execute 改命令、delete 改目标路径等）；不对称配置会让 langchain 抛
            # "Decision type ... is not allowed for tool ..." ValueError，整轮被弃。
            decisions = ["approve", "reject", "edit"]
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


def approve_prefix(state: dict, prefix: str, *, tool: str = "execute") -> None:
    """按命令前缀永久放行（工单 03）：写回 "<prefix> *": allow。

    字符串规则先升格为 {"*": 原值}（保持原语义），再追加前缀规则；
    fnmatch 最后匹配胜出（前缀规则追加在尾部，命中即 allow）。
    prefix 为 "*" 或提取不到 → 回落整工具 allow。
    """
    prefix = (prefix or "").strip()
    if prefix in ("", "*", "全"):
        # 空 / 提取失败 / 显式「全工具」→ 整工具 allow（与 commands.always_approve 语义对齐）
        apply_permission_override(state, tool, "allow")
        return
    rule = state["tools"].get(tool, state["default"])
    if isinstance(rule, dict):
        target = rule
    else:
        base = rule if isinstance(rule, str) and rule in VALID_ACTIONS else "ask"
        target = {"*": base}
        state["tools"][tool] = target
    target[f"{prefix} *"] = "allow"


class PermissionDenyMiddleware(GuardMiddleware):
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

    def block(self, view: ToolCallView) -> str | None:
        tool = view.name
        if tool not in GATED_TOOLS:
            return None
        if _action_for_args(self.state, tool, view.args) != "deny":
            return None
        return self._deny_message(view, tool)

    def _deny_message(self, view: ToolCallView, tool: str, *, prefix: str = "") -> str:
        """命中 deny 时生成给模型的错误消息。"""
        value = (
            command(view.args)
            if tool == "execute"
            else arg_value(view.args, "file_path", "path", "pattern", "command")
        )
        hook_msg = ""
        hook_rules = self.state.get("hooks") or []
        if hook_rules and tool in GATED_TOOLS:
            from src.permission_hooks import resolve_permission_hook

            hook = resolve_permission_hook(
                hook_rules,
                tool,
                view.args if isinstance(view.args, dict) else {},
                thread_id=str(self.state.get("thread_id") or ""),
                project_root=self.state.get("project_root"),
            )
            if hook and hook[0] == "deny" and hook[1]:
                hook_msg = f" Hook: {hook[1]}"
        lead = prefix or "Permission denied: 操作被 javis.json permissions 规则拒绝（deny）。"
        return (
            f"{lead}"
            f"工具 {tool}，参数 {value or view.args}。{hook_msg} 请更换方案或询问用户，不要重试相同调用。"
        )


def dump_permissions_json(permissions: dict, json_path: Path) -> None:
    """把当前内存 permissions 写回 javis.json（供 always approve 持久化）。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["permissions"] = permissions
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
