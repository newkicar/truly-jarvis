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
import hashlib
import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView, arg_value, command

# 需要审批的工具（deepagents 默认 gated tools）；read/glob/grep 只读工具不审批。
GATED_TOOLS = ("execute", "write_file", "edit_file", "delete")

VALID_ACTIONS = ("allow", "ask", "deny")

# ticket 05: state key holding profile-scoped (non-gated) rule tools.
EXTRA_RULE_TOOLS_KEY = "extra_rule_tools"

# YOLO 模式（tui-ux12）：线程级免审批。
# state["yolo_threads"] = 当前开启 YOLO 的 thread_id 集合（app 内共享、纯内存、
# 不落盘，重启即全关）。on/off 只动集合成员，从不修改 state["tools"] 规则，
# 因此 /yolo off 后原 permissions 规则原样生效（零快照、零 agent 重建）。
YOLO_THREADS_KEY = "yolo_threads"

# 替我审批模式（ADR-0014）：线程级「放行安全、拦住危险」。
# 与 yolo_threads 同惯例：纯内存、不落盘、重启全关；on/off 只动集合成员，
# 零 agent 重建。区别：yolo 全放行，proxy 仅按 proxy_auto_allow 的确定性
# 规则表放行安全动作（ADR-0014），危险动作仍走 HITL 审批。
PROXY_THREADS_KEY = "proxy_threads"

# 裁决层依赖（proxy.review，LLM 替我审批，工单 #18）：注入共享 permission
# state 的三个键。与上方 PROXY_THREADS_KEY（ADR-0014 确定性「替我审批」，
# 规则表转发）不同：裁决层由 #19 的 LLM 裁决 middleware 消费；#18 仅做
# 装配注入，这些键不参与 _action_for_args 门链路，纯 expand 零行为变化。
# state[PROXY_REVIEW_KEY] = 裁决层完整配置 dict（缺省 {}；#19 读到 enabled 才启用）；
# state[PROXY_REVIEW_MODEL_KEY] = 裁决层模型客户端（BaseChatModel 或 None）；
# state[PROXY_REVIEW_LAST_KEY] = 最近一次裁决记录 dict（#19 写 / #20 呈现；缺省 {}）；
# state[PROXY_REVIEW_OVERRIDES_KEY] = tid -> 已用一次性覆盖次数（#21 写，上限 10）；
# state[PROXY_REVIEW_BREAKERS_KEY] = tid -> {"streak","window","tripped"} 断路器（#21 写）。
PROXY_REVIEW_KEY = "proxy_review"
PROXY_REVIEW_MODEL_KEY = "proxy_review_model"
PROXY_REVIEW_LAST_KEY = "proxy_review_last"
PROXY_REVIEW_OVERRIDES_KEY = "proxy_review_overrides"
PROXY_REVIEW_BREAKERS_KEY = "proxy_review_breakers"

# /side 侧边会话（side-chat，2026-11-16）：线程级 side 标记。
# state["side_threads"] = 当前所有 side thread_id 集合；
# state["side_parents"] = side tid -> 主线 parent tid 映射。
# 与 yolo_threads 同惯例：纯内存、不落盘、重启全清；side_open/side_close
# 只动集合成员，零 agent 重建。
SIDE_THREADS_KEY = "side_threads"
SIDE_PARENTS_KEY = "side_parents"


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


def yolo_on(state: dict, thread_id: str) -> bool:
    """为指定 thread 开启 YOLO（幂等）。空 id 为 no-op，返回 False。

    Issue #9 互斥：YOLO 与 替我审批(proxy) 后开者为准——开 YOLO 自动关同 thread 的 proxy。
    """
    tid = str(thread_id or "")
    if not tid:
        return False
    state.setdefault(YOLO_THREADS_KEY, set()).add(tid)
    proxy_off(state, tid)  # Issue #9：互斥，开一个自动关另一个（同 thread）
    return True


def yolo_off(state: dict, thread_id: str) -> None:
    """为指定 thread 关闭 YOLO（幂等，缺失不报错）。空 id 为 no-op。"""
    tid = str(thread_id or "")
    if not tid:
        return
    threads = state.get(YOLO_THREADS_KEY)
    if isinstance(threads, set):
        threads.discard(tid)


def yolo_active(state: dict, thread_id: str) -> bool:
    """指定 thread 是否处于 YOLO 模式。

    空 id → False；state 缺 yolo_threads 键（旧引用防御）→ False。
    """
    tid = str(thread_id or "")
    if not tid:
        return False
    threads = state.get(YOLO_THREADS_KEY)
    return bool(threads is not None and tid in threads)

def proxy_on(state: dict, thread_id: str) -> bool:
    """为指定 thread 开启替我审批（幂等）。空 id 为 no-op，返回 False。

    Issue #9 互斥：YOLO 与 替我审批(proxy) 后开者为准——开 proxy 自动关同 thread 的 YOLO。
    """
    tid = str(thread_id or "")
    if not tid:
        return False
    state.setdefault(PROXY_THREADS_KEY, set()).add(tid)
    yolo_off(state, tid)  # Issue #9：互斥，开一个自动关另一个（同 thread）
    return True


def proxy_off(state: dict, thread_id: str) -> None:
    """为指定 thread 关闭替我审批（幂等，缺失不报错）。空 id 为 no-op。"""
    tid = str(thread_id or "")
    if not tid:
        return
    threads = state.get(PROXY_THREADS_KEY)
    if isinstance(threads, set):
        threads.discard(tid)


def proxy_active(state: dict, thread_id: str) -> bool:
    """指定 thread 是否处于替我审批模式。

    空 id → False；state 缺 proxy_threads 键（旧引用防御）→ False。
    """
    tid = str(thread_id or "")
    if not tid:
        return False
    threads = state.get(PROXY_THREADS_KEY)
    return bool(threads is not None and tid in threads)


def proxy_auto_allow(tool: str, args: dict, state: dict) -> bool:
    """替我审批的自动放行判定：放行安全的、拦住危险的（确定性规则表，见 ADR-0014）。

    - execute：仅当命令命中只读启发式表（与 heuristics 特性同源）才放行；
    - write_file/edit_file：仅当目标路径（resolve 后）位于项目根内才放行；
    - delete 与其他工具：绝不自动放行（留给人类审批）。
    """
    if tool == "execute":
        return heuristic_safe(command(args))
    if tool in ("write_file", "edit_file"):
        target = arg_value(args, "file_path", "path", "pattern", "command")
        if not isinstance(target, str) or not target:
            return False
        base = Path(state.get("project_root") or Path.cwd())
        p = Path(target)
        if not p.is_absolute():
            p = base / p
        try:
            return p.resolve().is_relative_to(base.resolve())
        except (OSError, RuntimeError, ValueError):
            return False
    return False


def side_open(state: dict, thread_id: str, parent: str) -> None:
    """登记一个 side 会话（幂等）。空 id 为 no-op。

    同时写 side_threads 集合与 side_parents 映射（parent 存主线 tid）。
    """
    tid = str(thread_id or "")
    if not tid:
        return
    state.setdefault(SIDE_THREADS_KEY, set()).add(tid)
    state.setdefault(SIDE_PARENTS_KEY, {})[tid] = str(parent or "")


def side_close(state: dict, thread_id: str) -> None:
    """注销一个 side 会话（幂等，缺失不报错）。空 id 为 no-op。"""
    tid = str(thread_id or "")
    if not tid:
        return
    threads = state.get(SIDE_THREADS_KEY)
    if isinstance(threads, set):
        threads.discard(tid)
    parents = state.get(SIDE_PARENTS_KEY)
    if isinstance(parents, dict):
        parents.pop(tid, None)


def side_active(state: dict, thread_id: str) -> bool:
    """指定 thread 是否处于 side 会话。

    空 id -> False；state 缺 side_threads 键（旧引用防御）-> False。
    """
    tid = str(thread_id or "")
    if not tid:
        return False
    threads = state.get(SIDE_THREADS_KEY)
    return bool(threads is not None and tid in threads)


def side_parent(state: dict, thread_id: str) -> str | None:
    """side 会话归属的主线 thread_id；非 side 会话 -> None。"""
    tid = str(thread_id or "")
    if not tid:
        return None
    parents = state.get(SIDE_PARENTS_KEY)
    if isinstance(parents, dict) and tid in parents:
        return parents[tid]
    return None


def side_child(state: dict, main_tid: str) -> str | None:
    """指定主线会话持有的 side 会话 tid；无 side / 无登记 -> None。

    遍历 side_parents 找 parent == main_tid 的登记项（纯读、零索引；
    主线同时挂多个 side 时返回首个登记者，与本线登记序一致）。
    """
    tid = str(main_tid or "")
    if not tid:
        return None
    parents = state.get(SIDE_PARENTS_KEY)
    if isinstance(parents, dict):
        for side, parent in parents.items():
            if str(parent) == tid:
                return side
    return None


def _current_turn_tid(state: dict) -> str:
    """工单 #4：当前回合真实 thread_id（门判定双真源收敛）。

    门读点（YOLO/proxy/side）优先取 thread-local——streaming.run_agent_turn
    在 worker 线程入口 set_current_thread_id（finally 成对清理）；thread-local
    按 OS 线程天然隔离，免疫并发 side/sched 回合对共享键 state["thread_id"]
    的覆写（覆写会让门落到错误 tid，而 TUI 徽标按显示线程判 → 门/徽标分歧）。
    无 thread-local（GUI 未走 run_agent_turn、测试直调）→ 回落共享键 = 旧行为，
    不回归。jump_in_queue 不 import permissions，函数内惰性 import 无循环依赖。
    """
    from src.jump_in_queue import get_current_thread_id
    return str(get_current_thread_id() or state.get("thread_id") or "")


def _action_for_args(state: dict, tool: str, args: dict) -> str:
    """按 state 当前规则 + 一次工具调用的 args 解析动作（allow/ask/deny）。

    YOLO 模式（tui-ux12）：当前 thread 命中 yolo_threads 时一律 "allow"
    （置于 hooks 解析之前 = 最高权限语义，hook 判定同样 bypass）；
    ask 中断（when 谓词）与 deny 拦截（PermissionDenyMiddleware.block）
    双路汇入此函数，一处短路同时消灭「审批弹窗」与「拒绝」。

    Hook 优先于 javis.json permissions（Codex: Hooks → rules → User）。
    """
    if yolo_active(state, _current_turn_tid(state)):
        return "allow"
    hook_rules = state.get("hooks") or []
    if hook_rules and tool in GATED_TOOLS:
        from src.permission_hooks import resolve_permission_hook

        hook = resolve_permission_hook(
            hook_rules,
            tool,
            args if isinstance(args, dict) else {},
            thread_id=_current_turn_tid(state),
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
    # 替我审批（ADR-0014）：当前 thread 命中 proxy_threads 时，安全动作
    # （execute 命中只读启发式 / 项目根内写编辑）直接放行；危险动作
    # （delete / 项目根外写 / execute 未命中启发式）仍走 ask 中断留给人类。
    # deny 已在规则解析阶段定案、绝不被覆盖；yolo 短路（函数顶）优先于本块。
    if (
        action == "ask"
        and proxy_active(state, _current_turn_tid(state))
        and proxy_auto_allow(tool, args if isinstance(args, dict) else {}, state)
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

    #19: 基础动作解析为 ask 时，先过 proxy.review 裁决层（惰性 import 防
    循环依赖）：当前线程「替我审批」+ 裁决层 enabled + 有模型，且裁决
    allow → when 返回 False（自动放行，不中断）；裁决层 inert / 裁决
    失败 / 裁决 ask → 返回 True 维持原审批（fail-closed）。YOLO 短路 / 地板 /
    显式 deny / 只读启发式均在 ask 之前定案，!= "ask" 短路保证这些
    路径正交（零模型调用）。
    """
    def when(request) -> bool:
        args = _extract_args_from_request(request)
        if _action_for_args(state, tool, args) != "ask":
            return False
        from src.proxy_reviewer import proxy_review_upgrade  # 惰性 import 防循环

        return not proxy_review_upgrade(state, tool, args, request)
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
    proxy_review: dict | None = None,
    proxy_review_model: object = None,
) -> tuple[dict, dict]:
    """把 javis.json 的 permissions 配置转成 deepagents 的 interrupt_on。

    返回 (interrupt_on, state)：
      - interrupt_on：传给 create_deep_agent 的 dict。
      - state：{"tools": {tool: rule}, "default": rule} 可变引用，运行时改它即改行为。

    permissions 缺省/为 None 时，所有 gated tool 默认 "ask"（每次都审批）。
    proxy_review / proxy_review_model（#18，纯 expand）：裁决层配置与模型客户端，
    注入 state 的 PROXY_REVIEW_KEY / PROXY_REVIEW_MODEL_KEY，供 #19 裁决 middleware 消费。
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
        "yolo_threads": set(),
        PROXY_THREADS_KEY: set(),
        SIDE_THREADS_KEY: set(),
        SIDE_PARENTS_KEY: {},
        EXTRA_RULE_TOOLS_KEY: (),
        PROXY_REVIEW_KEY: proxy_review if isinstance(proxy_review, dict) else {},
        PROXY_REVIEW_MODEL_KEY: proxy_review_model,
        PROXY_REVIEW_LAST_KEY: {},
        PROXY_REVIEW_OVERRIDES_KEY: {},
        PROXY_REVIEW_BREAKERS_KEY: {},
    }
    return _build_interrupt_on(state), state


def build_permission_interrupts_from_state(state: dict) -> dict:
    """从已构造的 state 重建 interrupt_on（供外部复用同一 state 引用时使用）。"""
    state.setdefault(YOLO_THREADS_KEY, set())
    state.setdefault(PROXY_THREADS_KEY, set())
    state.setdefault(SIDE_THREADS_KEY, set())
    state.setdefault(SIDE_PARENTS_KEY, {})
    state.setdefault(EXTRA_RULE_TOOLS_KEY, ())
    state.setdefault(PROXY_REVIEW_KEY, {})
    state.setdefault(PROXY_REVIEW_MODEL_KEY, None)
    state.setdefault(PROXY_REVIEW_LAST_KEY, {})
    state.setdefault(PROXY_REVIEW_OVERRIDES_KEY, {})
    state.setdefault(PROXY_REVIEW_BREAKERS_KEY, {})
    return _build_interrupt_on(state)


def _build_interrupt_on(state: dict) -> dict:
    interrupt_on: dict = {}
    tools = tuple(GATED_TOOLS) + tuple(state.get(EXTRA_RULE_TOOLS_KEY) or ())
    for tool in dict.fromkeys(tools):
        rule = state["tools"].get(tool, state["default"])
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


def build_permission_interrupts_extended(
    permissions: dict | None,
    *,
    extra_tools: tuple = (),
    hooks: dict | None = None,
    project_root: Path | None = None,
    proxy_review: dict | None = None,
    proxy_review_model: object = None,
) -> tuple[dict, dict]:
    """ticket 05: extend gated rules to profile-scoped tools (fail-closed ask).

    Extra tools without an explicit rule default to "ask" (never inherit a
    "*" default that may be "allow"); explicit rules are kept.
    """
    interrupt_on, state = build_permission_interrupts(
        permissions,
        hooks=hooks,
        project_root=project_root,
        proxy_review=proxy_review,
        proxy_review_model=proxy_review_model,
    )
    extra = tuple(dict.fromkeys(extra_tools))
    pool = permissions or {}
    for tool in extra:
        state["tools"].setdefault(tool, pool.get(tool) or "ask")
    state[EXTRA_RULE_TOOLS_KEY] = extra
    return _build_interrupt_on(state), state


def inject_proxy_review_deps(
    state: dict,
    review_config: object,
    review_model: object = None,
) -> None:
    """#18: 把裁决层依赖幂等注入共享 permission state。

    覆写两个键：PROXY_REVIEW_KEY（非 dict 配置归一为 {}）与
    PROXY_REVIEW_MODEL_KEY（模型客户端或 None）；并回填 PROXY_REVIEW_LAST_KEY
    （最近裁决记录 dict，缺省 {}）与 #21 的 PROXY_REVIEW_OVERRIDES_KEY /
    PROXY_REVIEW_BREAKERS_KEY（一次性覆盖计数 / 线程级断路器，缺省 {}）。
    纯扩键：这些键不参与
    _action_for_args 门链路，既有 allow/ask/deny/YOLO/proxy_threads
    行为零变化。外部 state（main.py 预建）与 from_state 回填的
    旧形态 state 注入后同样完整。
    """
    if state is None:
        return
    state[PROXY_REVIEW_KEY] = review_config if isinstance(review_config, dict) else {}
    state[PROXY_REVIEW_MODEL_KEY] = review_model
    state.setdefault(PROXY_REVIEW_LAST_KEY, {})
    state.setdefault(PROXY_REVIEW_OVERRIDES_KEY, {})
    state.setdefault(PROXY_REVIEW_BREAKERS_KEY, {})


def merge_permissions_deny_wins(
    base: dict | None,
    extra_rules: dict | None,
    deny_tools: tuple = (),
) -> dict:
    """ticket 05: profile rules may only tighten, never relax project rules.

    - a base "deny" survives any non-deny profile rule for that tool;
    - any other profile rule overwrites the base value;
    - deny_tools are forced to "deny" last. Inputs are not mutated.
    """
    merged: dict = dict(base or {})
    for key, rule in (extra_rules or {}).items():
        if merged.get(key) == "deny" and rule != "deny":
            continue
        merged[key] = rule
    for tool in deny_tools or ():
        if merged.get(tool) != "deny":
            merged[tool] = "deny"
    return merged


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
        extra = self.state.get(EXTRA_RULE_TOOLS_KEY) or ()
        if tool not in GATED_TOOLS and tool not in extra:
            return None
        if _action_for_args(self.state, tool, view.args) != "deny":
            return None
        self._record_deny(view, tool)
        return self._deny_message(view, tool)

    def _record_deny(self, view: ToolCallView, tool: str) -> None:
        """ticket 05: best-effort deny audit line (hash + length, never raw args)."""
        try:
            value = (
                command(view.args)
                if tool == "execute"
                else arg_value(view.args, "file_path", "path", "pattern", "command")
            )
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": tool,
                "action": "deny",
                "prefix": extract_command_prefix(value) if tool == "execute" else "",
                "value_hash": hashlib.sha1(value.encode("utf-8", "replace")).hexdigest()[:12],
                "value_len": len(value),
                "thread_id": _current_turn_tid(self.state),
            }
            from src.project_paths import user_home

            audit_dir = user_home() / "audit"
            audit_dir.mkdir(parents=True, exist_ok=True)
            with (audit_dir / "permissions.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            from src.profiles.observability import ops_event

            ops_event(
                "tool_permission_denied",
                tool=tool,
                prefix=record["prefix"],
                thread_id=record["thread_id"],
            )
        except Exception:
            pass

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
                thread_id=_current_turn_tid(self.state),
                project_root=self.state.get("project_root"),
            )
            if hook and hook[0] == "deny" and hook[1]:
                hook_msg = f" Hook: {hook[1]}"
        lead = prefix or "Permission denied: 操作被 javis.json permissions 规则拒绝（deny）。"
        return (
            f"{lead}"
            f"工具 {tool}，参数 {value or view.args}。{hook_msg} 请更换方案或询问用户，不要重试相同调用。"
        )


class SideTaskGuardMiddleware(GuardMiddleware):
    """side 会话工具守卫：side 会话只读（仅读/搜，对标 codex side）。
    task（sub-agents）与 execute（命令执行）被拦截；读/搜工具放行。

    挂在主代理 wrap_tool_call / awrap_tool_call（工具执行前），state 与
    interrupt_on 共享同一引用 —— side_open/side_close 即时生效，无需重建 agent。
    门读点（工单 #4）改读 thread-local（streaming.run_agent_turn 每回合
    入口 set、finally 清），免疫并发 side/sched 回合对共享键 state["thread_id"]
    的覆写；未走 run_agent_turn 的路径回落共享键（旧行为），不回归。
    """

    def __init__(self, state: dict):
        super().__init__()
        self.state = state

    @property
    def name(self) -> str:
        return "side-task-guard"

    def block(self, view: ToolCallView) -> str | None:
        if view.name not in ("task", "execute"):
            return None
        if not side_active(self.state, _current_turn_tid(self.state)):
            return None
        if view.name == "task":
            return ("Error: side 会话中不可用 sub-agents（task 工具）。"
                    "/side close 返回主线后再用。")
        return ("Error: side 会话为只读（仅读/搜，对标 codex side），execute 被禁用。"
                "/side close 返回主线后再执行命令。")


def dump_permissions_json(permissions: dict, json_path: Path) -> None:
    """把当前内存 permissions 写回 javis.json（供 always approve 持久化）。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["permissions"] = permissions
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
