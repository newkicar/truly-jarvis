"""CLI/TUI 共用的 stream_events(v3) 消费与 HITL 决策组装。"""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from src import commands, resilience

REJECT_MESSAGE = "用户拒绝了该操作，请更换方案或询问用户。不要重试相同调用。"

# tui-ux10: Esc drain 看门狗轮询间隔（秒）——取消后立即请求 drain，不等 item 到达。
_DRAIN_WATCHDOG_INTERVAL_S = 0.05

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
    if "Unexpected human decision" in msg or "is not allowed for tool" in msg:
        return (
            "审批决策与工具配置不匹配（该决策类型未被当前工具允许，本轮已中止）。\n"
            "请重新执行审批；若反复出现，请检查 jarvis.json 的 permissions 配置。"
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
                    commands.always_approve(
                        permission_state,
                        inv.name,
                        args=inv.args,
                        prefix=result.get("prefix"),
                    )
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
            from src.permissions import GATED_TOOLS, extract_command_prefix
            from src.tool_call import command as _command

            if permission_state is None or inv.name not in GATED_TOOLS:
                print(f"    无法持久化 {inv.name} 的 always approve（非 gated tool 或未配置）")
                return {"decision": "always_approve"}
            if inv.name == "execute":
                default = extract_command_prefix(_command(inv.args or {}))
                p = read(
                    f"    将写回 '{default} *': allow，命令前缀（回车=默认；输入「全」= 整工具） > "
                ).strip()
                if not p:
                    p = default
                elif p == "全":
                    p = "*"
                return {"decision": "always_approve", "prefix": p}
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
    control: Any = None,
) -> int:
    """消费 stream_events interleave 循环，返回 message delta 计数。

    tui-ux6 #03（ADR-0008）：取消命中时若 control 非 None，request_drain("user-cancel")
    请求图排空——正在执行的当前 superstep（含慢工具/命令）跑完后停止，后续步骤被跳过，
    流最终抛 GraphDrained 自然上抛；drain 期间抑制全部后续回调。control=None 保持旧
    语义：取消命中立即返回（图继续按自身节奏跑满）。
    """
    consumed = 0
    subagent_depth = 0
    draining = False
    for kind, item in stream.interleave("messages", "tool_calls", "subagents"):
        if is_cancelled() and not draining:
            if on_cancelled:
                on_cancelled()
            if control is None:
                return consumed
            control.request_drain("user-cancel")
            draining = True
            continue
        if draining:
            continue
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
                if is_cancelled() and not draining:
                    if on_cancelled:
                        on_cancelled()
                    if control is None:
                        return consumed
                    control.request_drain("user-cancel")
                    draining = True
                if draining:
                    break
                consumed += 1
                segment.append(delta)
                callbacks["on_message_delta"](delta)
            if draining:
                continue
            if segment and callbacks.get("on_message_end"):
                callbacks["on_message_end"]("".join(segment))
    return consumed


# #03: 图片拒绝判定（多模态 auto 回落的触发条件）。
# 端点 400/415/422 报错文本未必含 "image"/"vision"（如 OpenAI 兼容网关的
# 通用 Bad Request），关键词集放宽 + 状态码兜底；命中则纯文本重试一次。
_IMAGE_REJECT_KEYWORDS = (
    "image",
    "vision",
    "multimodal",
    "modality",
    "unsupported media",
    "unsupported content",
    "not supported",
    "not support",
    "cannot be processed",
    "bad request",
    "不支持",
    "无法处理",
    "图片",
    "图像",
)


def _looks_like_image_rejection(exc: BaseException) -> bool:
    """判断异常是否指向图片输入被拒（关键词或 4xx 状态码）。"""
    text = str(exc).lower()
    if any(k in text for k in _IMAGE_REJECT_KEYWORDS):
        return True
    return getattr(exc, "status_code", None) in (400, 415, 422)


def run_agent_turn(
    agent,
    thread_id: str,
    user_input: str | list | None = None,
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
    model_image_input: str = "auto",
    user_input_fallback: str | None = None,
) -> bool:
    """跑一轮对话或 checkpoint 重跑（含 HITL resume 循环）。返回 True=正常结束，False=放弃/取消。

    韧性：retryable API 错误按决策表退避重试（状态经 callbacks["on_status"] 可见），
    步数超限软着陆收尾而非裸异常。
    """
    from langgraph.errors import GraphDrained, GraphRecursionError
    from langgraph.runtime import RunControl
    from langgraph.types import Command
    from src.permissions import sync_permission_context

    sync_permission_context(
        permission_state, thread_id=thread_id, project_root=project_root
    )

    max_steps = max(10, int(max_steps))
    base_config = {**commands.thread_config(thread_id), "recursion_limit": max_steps}
    resume = None
    _image_fallback_done = False  # #03: 多模态 auto 回落只重试一次
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
        # tui-ux6 #03: 每个 stream 尝试（含 HITL resume 每轮）独立 RunControl——
        # 本 attempt 的 Esc drain 不泄漏到下一次 stream。
        control = RunControl()
        stream = agent.stream_events(
            stream_input, version="v3", config=config, control=control
        )
        # tui-ux10: CI langgraph 1.2.16 事件发射时序回归防御——慢工具运行期间
        # 无 item 到达，item 边界 drain 请求可能晚于 tick 检查点；看门狗以 50ms
        # 轮询 is_cancelled，命中即 request_drain（request_drain 线程安全；item
        # 边界 drain 保留作双保险）。daemon 线程 + finally stop/join，无泄漏。
        stop = threading.Event()

        def _drain_watchdog() -> None:
            while not stop.is_set():
                stop.wait(_DRAIN_WATCHDOG_INTERVAL_S)
                if not stop.is_set() and is_cancelled():
                    control.request_drain("user-cancel")
                    stop.set()
                    return

        wd = threading.Thread(
            target=_drain_watchdog, name="jarvis-drain-watchdog", daemon=True
        )
        wd.start()
        try:
            consumed = consume_stream_events(
                stream,
                callbacks,
                is_cancelled=is_cancelled,
                on_cancelled=on_cancelled,
                control=control,
            )
        finally:
            stop.set()
            wd.join(timeout=0.2)
        return consumed, stream

    # 重试仅针对全新用户轮次与 checkpoint 重放（resume 语义不可安全重放）。
    attempt = 0

    def _stream_with_resilience(stream_input: Any, config: dict):
        nonlocal attempt
        while True:
            try:
                return _run_stream(stream_input, config)
            except GraphDrained:
                # tui-ux6 #03: Esc drain 取消不是 API 错误——不进重试/退避路径，
                # checkpoint 清理由 run_agent_turn 外层 finally 统一处理。
                raise
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
                    **commands.thread_config(thread_id, checkpoint_id),
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
                # 到顶不许摆烂（对标 opencode）：强制一次结构化交接（不写历史）。
                handoff = commands.force_handoff(agent, thread_id, max_steps)
                if handoff:
                    if on_fallback_message:
                        on_fallback_message(handoff)
                    else:
                        print(handoff)
                    if callbacks.get("on_status"):
                        callbacks["on_status"](
                            f"任务步数超过上限 {max_steps}，已生成交接摘要。"
                            "如需继续，调高 javis.json 的 execution.max_steps 或开新会话。"
                        )
                else:
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
            except Exception as exc:
                # #03: 多模态能力门 auto 回落——模型拒绝图片时，改发「路径引用」纯文本重试一次；
                # 其余异常保持原语义（清理 checkpoint 后上抛，由 presenter 显示错误）。
                if (
                    not _image_fallback_done
                    and isinstance(user_input, list)
                    and model_image_input == "auto"
                    and user_input_fallback is not None
                    and _looks_like_image_rejection(exc)
                ):
                    _image_fallback_done = True
                    user_input = user_input_fallback
                    status_cb = callbacks.get("on_status")
                    if status_cb:
                        status_cb("模型端点拒绝图片输入，已改为路径引用自动重试")
                    continue
                # 内部 _stream_with_resilience 上抛前已 finalize，这里不重复清理。
                raise
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
    except GraphDrained:
        # tui-ux6 #03: Esc drain（ADR-0008）——图按「当前 superstep 跑完即停」语义停止；
        # 不重试、不交接（与步数超限 force_handoff 不同路）；finally 走 finalize + on_turn_incomplete。
        outcome = "cancel"
        return False
    finally:
        if outcome != "complete":
            _finalize_if_needed()
