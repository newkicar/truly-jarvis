"""CLI/TUI 共用的 stream_events(v3) 消费与 HITL 决策组装。"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from src import commands, resilience

REJECT_MESSAGE = "用户拒绝了该操作，请更换方案或询问用户。不要重试相同调用。"

StreamCallbacks = dict[str, Callable[..., None]]


def format_agent_error(exc: BaseException) -> str:
    """把 agent/API 异常转为 TUI/CLI 可读短句。"""
    name = type(exc).__name__
    msg = str(exc).replace("\n", " ")
    if len(msg) > 400:
        msg = msg[:400] + "…"
    if "BadRequest" in name or "400" in msg:
        return (
            f"API 请求失败：{msg}\n"
            "常见原因：① opencode 端点偶发 400（可重试）；"
            "② 当前会话 checkpoint 已损坏（执行 /delete-session 或 python -m src.main -n --cli 开新会话）；"
            "③ .env 的 MODEL_ID 与套餐不一致。"
        )
    if "Authentication" in name or "401" in msg or "403" in msg:
        return f"鉴权失败：{msg}\n请检查 .env 的 API_KEY / BASE_URL。"
    return f"{name}: {msg}"

_SUBAGENT_ACTIVE = frozenset({"started", "running", "start"})
_SUBAGENT_DONE = frozenset({"completed", "failed", "done", "error"})


def iter_text_deltas(chunks) -> list[str]:
    """从 stream_events message.text 提取字符串 delta，跳过 tool_call blocks。"""
    out: list[str] = []
    for chunk in chunks:
        if isinstance(chunk, str):
            if chunk:
                out.append(chunk)
        elif isinstance(chunk, dict):
            if chunk.get("type") == "text":
                text = chunk.get("text", "")
                if text:
                    out.append(str(text))
            continue
        elif isinstance(chunk, list):
            out.extend(iter_text_deltas(chunk))
    return out


def _tool_output(item) -> str | None:
    """从 stream tool_calls 项提取输出文本。"""
    if getattr(item, "error", None):
        err = item.error
        return str(getattr(err, "message", err) or err)
    out = getattr(item, "output", None)
    if out is not None:
        return str(out)
    deltas = getattr(item, "output_deltas", None)
    if deltas:
        return "".join(str(d) for d in deltas)
    return None


def decision_from_choice(
    choice: str,
    *,
    name: str,
    args: dict | None,
    permission_state: dict | None,
    edited: dict | None = None,
) -> dict | None:
    """把单次审批选择转成 resume decisions 条目；cancel/abandon 返回 None。"""
    if choice == "approve":
        return {"type": "approve"}
    if choice == "reject":
        return {"type": "reject", "message": REJECT_MESSAGE}
    if choice == "always_approve":
        if permission_state is not None:
            commands.always_approve(permission_state, name)
        return {"type": "approve"}
    if choice == "edit":
        return {
            "type": "edit",
            "edited_action": {"name": name, "args": edited or dict(args or {})},
        }
    return None


def interrupt_action_key(action: dict) -> str:
    """HITL action_requests 项的稳定键（用于 pending 去重 / replay 过滤）。"""
    name = action.get("name", "?")
    args = action.get("args") or {}
    explicit = action.get("id") or action.get("call_id")
    if explicit:
        return str(explicit)
    return f"{name}:{json.dumps(args, sort_keys=True, default=str)}"


def filter_pending_interrupts(interrupts, resolved_keys: set[str] | frozenset[str] | None):
    """去掉已 resolved 的 action_requests；若全无 pending 则返回空列表。"""
    if not interrupts:
        return []
    resolved = resolved_keys or frozenset()
    filtered = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None) or {}
        pending = [
            action
            for action in value.get("action_requests", [])
            if interrupt_action_key(action) not in resolved
        ]
        if not pending:
            continue
        filtered.append(type("I", (), {"value": {**value, "action_requests": pending}})())
    return filtered


def collect_interrupt_decisions(
    interrupts,
    ask_action: Callable[[commands.ToolInvocation], dict | None],
    *,
    permission_state: dict | None = None,
    on_always_approve: Callable[[str], None] | None = None,
) -> dict | None:
    """逐条中断收集决策，返回 {"decisions": [...]} 或 None（放弃本轮）。"""
    from src.permission_hooks import resolve_permission_hook

    decisions: list[dict] = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None) or {}
        for action in value.get("action_requests", []):
            inv = commands.ToolInvocation.from_action(action)
            if permission_state:
                hook = resolve_permission_hook(
                    permission_state.get("hooks") or [],
                    inv.name,
                    inv.args or {},
                    thread_id=str(permission_state.get("thread_id") or ""),
                    project_root=permission_state.get("project_root"),
                )
                if hook is not None:
                    hook_decision, hook_msg = hook
                    if hook_decision == "allow":
                        decisions.append({"type": "approve"})
                        continue
                    if hook_decision == "deny":
                        msg = hook_msg or REJECT_MESSAGE
                        decisions.append({"type": "reject", "message": msg})
                        continue
            result = ask_action(inv)
            if result is None:
                return None
            decision = result.get("decision")
            if decision == "approve":
                decisions.append({"type": "approve"})
            elif decision == "reject":
                decisions.append({"type": "reject", "message": REJECT_MESSAGE})
            elif decision == "always_approve":
                if permission_state is not None:
                    commands.always_approve(permission_state, inv.name)
                    if on_always_approve:
                        on_always_approve(inv.name)
                decisions.append({"type": "approve"})
            elif decision == "edit":
                edited = result.get("edited") or {}
                decisions.append(
                    decision_from_choice(
                        "edit", name=inv.name, args=inv.args, permission_state=None, edited=edited
                    )
                )
            else:
                return None
    return {"decisions": decisions}


def cli_prompt_action(
    inv: commands.ToolInvocation,
    *,
    permission_state: dict | None,
    input_fn: Callable[[str], str] | None = None,
    on_always_approve: Callable[[str], None] | None = None,
    vault_path=None,
    workspace_root=None,
) -> dict | None:
    """CLI 终端逐条审批，返回 modal 同构结果 dict。"""
    from src.tui_format import permission_preview

    read = input_fn or input
    print(f"\n  [审批] {inv.name}")
    preview = permission_preview(
        inv,
        vault_path=vault_path,
        workspace_root=workspace_root,
    )
    if preview:
        print(preview)
    elif inv.args:
        for k, v in inv.args.items():
            print(f"    {k}: {str(v)[:120]}")
    while True:
        choice = read(
            "    操作: [y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮) > "
        ).strip().lower()
        if choice == "y":
            return {"decision": "approve"}
        if choice == "n":
            return {"decision": "reject"}
        if choice == "a":
            if permission_state is not None and commands.always_approve(permission_state, inv.name):
                if on_always_approve:
                    on_always_approve(inv.name)
            else:
                print(f"    无法持久化 {inv.name} 的 always approve（非 gated tool）")
            return {"decision": "always_approve"}
        if choice == "e":
            print("    编辑参数（留空使用原值）:")
            edited = dict(inv.args or {})
            for k in list(edited.keys()):
                new_v = read(f"    {k} [原: {str(edited[k])[:60]}] > ").strip()
                if new_v:
                    edited[k] = new_v
            return {"decision": "edit", "edited": edited}
        if choice == "q":
            return None
        print("    无效输入")


def consume_stream_events(
    stream,
    callbacks: StreamCallbacks,
    *,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_cancelled: Callable[[], None] | None = None,
) -> int:
    """消费 stream_events interleave 循环，返回 message delta 计数。"""
    consumed = 0
    subagent_depth = 0
    for kind, item in stream.interleave("messages", "tool_calls", "subagents"):
        if is_cancelled():
            if on_cancelled:
                on_cancelled()
            return consumed
        if kind == "subagents":
            status = str(getattr(item, "status", "") or "").lower()
            name = getattr(item, "name", "?")
            if status in _SUBAGENT_ACTIVE:
                subagent_depth += 1
            callbacks["on_subagent"](name, status, subagent_depth)
            if status in _SUBAGENT_DONE:
                subagent_depth = max(0, subagent_depth - 1)
            # 子代理项内嵌工具（fan-out 等场景）
            nested = getattr(item, "tool_calls", None) or []
            for tc in nested:
                tc_name = getattr(tc, "tool_name", None) or getattr(tc, "name", "?")
                tc_args = str(getattr(tc, "input", getattr(tc, "args", "")))
                tc_err = bool(getattr(tc, "error", None))
                tc_out = _tool_output(tc)
                callbacks["on_tool_call"](tc_name, tc_args, tc_err, tc_out, subagent_depth)
        elif kind == "tool_calls":
            callbacks["on_tool_call"](
                getattr(item, "tool_name", "?"),
                str(getattr(item, "input", "")),
                bool(getattr(item, "error", None)),
                _tool_output(item),
                subagent_depth,
            )
        else:
            segment: list[str] = []
            for delta in iter_text_deltas(item.text):
                if is_cancelled():
                    if on_cancelled:
                        on_cancelled()
                    return consumed
                consumed += 1
                segment.append(delta)
                callbacks["on_message_delta"](delta)
            if segment and callbacks.get("on_message_end"):
                callbacks["on_message_end"]("".join(segment))
    return consumed


def run_agent_turn(
    agent,
    thread_id: str,
    user_input: str | None = None,
    *,
    checkpoint_id: str | None = None,
    handle_interrupts: Callable[[Any], dict | None],
    callbacks: StreamCallbacks,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_fallback_message: Callable[[str], None] | None = None,
    on_stream_start: Callable[[], None] | None = None,
    on_cancelled: Callable[[], None] | None = None,
    on_turn_incomplete: Callable[[], None] | None = None,
    permission_state: dict | None = None,
    project_root=None,
    max_steps: int = 200,
) -> bool:
    """跑一轮对话或 checkpoint 重跑（含 HITL resume 循环）。返回 True=正常结束，False=放弃/取消。

    韧性：retryable API 错误按决策表退避重试（状态经 callbacks["on_status"] 可见），
    步数超限软着陆收尾而非裸异常。
    """
    from langgraph.errors import GraphRecursionError
    from langgraph.types import Command
    from src.permissions import sync_permission_context

    sync_permission_context(
        permission_state, thread_id=thread_id, project_root=project_root
    )

    max_steps = max(10, int(max_steps))
    base_config = {"configurable": {"thread_id": thread_id}, "recursion_limit": max_steps}
    resume = None
    replay_pending = checkpoint_id is not None
    outcome = "complete"

    def _finalize_if_needed() -> None:
        commands.finalize_turn(agent, thread_id)
        if on_turn_incomplete:
            on_turn_incomplete()

    def _cancellable_sleep(seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if is_cancelled():
                return False
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))
        return True

    if replay_pending:
        saved = commands.completed_turn_checkpoint(agent, thread_id, checkpoint_id)
        if saved is not None:
            if on_stream_start:
                on_stream_start()
            text = commands.render((saved.values or {}).get("messages") or [])
            if text:
                if callbacks.get("on_message_end"):
                    callbacks["on_message_delta"](text)
                    callbacks["on_message_end"](text)
                elif on_fallback_message:
                    on_fallback_message(text)
                else:
                    callbacks["on_message_delta"](text)
            return True
    def _run_stream(stream_input: Any, config: dict):
        stream = agent.stream_events(stream_input, version="v3", config=config)
        consumed = consume_stream_events(
            stream, callbacks, is_cancelled=is_cancelled, on_cancelled=on_cancelled
        )
        return consumed, stream

    # 重试仅针对全新用户轮次与 checkpoint 重放（resume 语义不可安全重放）。
    attempt = 0

    def _stream_with_resilience(stream_input: Any, config: dict):
        nonlocal attempt
        while True:
            try:
                return _run_stream(stream_input, config)
            except Exception as exc:
                should_retry = (
                    not is_cancelled()
                    and not resume
                    and resilience.classify_error(exc) == "retryable"
                    and attempt < resilience.RETRY_MAX_ATTEMPTS - 1
                )
                if not should_retry:
                    # 不重试的异常（fatal/auth/取消/resume）：先清理 checkpoint 再上抛，
                    # 避免脏状态污染下一轮（恢复原 400-repair 时代的行为）。
                    commands.finalize_turn(agent, thread_id)
                    raise
                commands.finalize_turn(agent, thread_id)
                wait = resilience.backoff_delay(
                    attempt, retry_after=resilience.extract_retry_after(exc)
                )
                status_cb = callbacks.get("on_status")
                if status_cb:
                    status_cb(
                        f"API 中断（{type(exc).__name__}），{wait:.0f}s 后重试"
                        f"（{attempt + 1}/{resilience.RETRY_MAX_ATTEMPTS}）"
                    )
                if not _cancellable_sleep(wait):
                    raise
                attempt += 1

    try:
        while not is_cancelled():
            if on_stream_start:
                on_stream_start()
            if resume:
                stream_input: Any = Command(resume=resume)
                config = base_config
            elif replay_pending:
                stream_input = None
                config = {
                    "configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id},
                    "recursion_limit": max_steps,
                }
                replay_pending = False
            else:
                commands.finalize_turn(agent, thread_id)
                stream_input = {"messages": [{"role": "user", "content": user_input}]}
                config = base_config
            try:
                consumed, stream = _stream_with_resilience(stream_input, config)
            except GraphRecursionError:
                commands.finalize_turn(agent, thread_id)
                msg = (
                    f"任务步数超过上限 {max_steps}，已强制收尾。"
                    "可 /history 查看进度；如需更长执行，调高 javis.json 的 execution.max_steps。"
                )
                if callbacks.get("on_status"):
                    callbacks["on_status"](msg)
                elif on_fallback_message:
                    on_fallback_message(msg)
                outcome = "abandon"
                return False
            if is_cancelled():
                outcome = "cancel"
                return False

            if not consumed and on_fallback_message:
                final_state = stream.output
                final_text = commands.render(final_state["messages"]) if final_state else ""
                if final_text:
                    on_fallback_message(final_text)

            if not getattr(stream, "interrupted", False) or not getattr(stream, "interrupts", None):
                return True

            resume = handle_interrupts(stream.interrupts)
            if resume is None:
                outcome = "abandon"
                return False
        outcome = "cancel"
        return False
    finally:
        if outcome != "complete":
            _finalize_if_needed()
