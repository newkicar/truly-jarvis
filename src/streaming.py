"""CLI/TUI 共用的 stream_events(v3) 消费与 HITL 决策组装。"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src import commands

REJECT_MESSAGE = "用户拒绝了该操作，请更换方案或询问用户。不要重试相同调用。"

StreamCallbacks = dict[str, Callable[..., None]]

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


def collect_interrupt_decisions(
    interrupts,
    ask_action: Callable[[commands.ToolInvocation], dict | None],
    *,
    permission_state: dict | None = None,
    on_always_approve: Callable[[str], None] | None = None,
) -> dict | None:
    """逐条中断收集决策，返回 {"decisions": [...]} 或 None（放弃本轮）。"""
    decisions: list[dict] = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None) or {}
        for action in value.get("action_requests", []):
            inv = commands.ToolInvocation.from_action(action)
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
    user_input: str,
    *,
    handle_interrupts: Callable[[Any], dict | None],
    callbacks: StreamCallbacks,
    is_cancelled: Callable[[], bool] = lambda: False,
    on_fallback_message: Callable[[str], None] | None = None,
    on_stream_start: Callable[[], None] | None = None,
    on_cancelled: Callable[[], None] | None = None,
) -> bool:
    """跑一轮对话（含 HITL resume 循环）。返回 True=正常结束，False=放弃/取消。"""
    from langgraph.types import Command

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}
    resume = None
    while not is_cancelled():
        if on_stream_start:
            on_stream_start()
        stream = agent.stream_events(
            Command(resume=resume) if resume else {"messages": [{"role": "user", "content": user_input}]},
            version="v3",
            config=config,
        )
        consumed = consume_stream_events(
            stream, callbacks, is_cancelled=is_cancelled, on_cancelled=on_cancelled
        )
        if is_cancelled():
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
            return False
    return False
