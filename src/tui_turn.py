"""回合编排 presenter（架构评审候选①）：per-turn 流式状态与回调的唯一归属地。

JarvisApp._stream_agent 原为 155 行方法内嵌 12 个闭包，共享 6 份 per-turn
可变状态。本 module 把它们提升为 TurnPresenter 的实例属性与方法——UI 动作
仍经由宿主 app 的既有方法完成（call_from_thread 编组不变），JarvisApp 只留
薄壳入口。渲染格式化继续走 tui_format 纯函数。
"""
from __future__ import annotations

from time import time

from textual.worker import get_current_worker
from textual.widgets import RichLog

from src import commands, streaming
from src.plan_mode import current_mode
from src.tui_format import AiStreamThrottler, format_tool_call


class TurnPresenter:
    """单轮对话的流式呈现与编排。

    持有 per-turn 可变状态（throttler / stream_active / cancel_notified /
    start_mode），把原 _stream_agent 的闭包团变成方法；宿主 app 引用仅在
    编排边界上使用。
    """

    def __init__(self, app, user_input: str | None, checkpoint_id: str | None):
        self.app = app
        self.user_input = user_input
        self.checkpoint_id = checkpoint_id
        self.started = time()
        # 模式标注取流开始时的快照（中途 Tab 切换不改变本轮回复的归属）；
        # 先于 log 的 UI 往返捕获，与重构前顺序一致。
        self.start_mode = current_mode(app.permission_state)
        self.log: RichLog | None = app.call_from_thread(
            app.query_one, "#messages", RichLog
        )
        self.throttler = AiStreamThrottler()
        self.stream_active = False
        self.cancel_notified = False
        self.worker = None  # run() 进入 worker 线程后填充

    # ---- 基础设施 ----

    def cancelled(self) -> bool:
        return bool(self.worker and self.worker.is_cancelled)

    def write_line(self, text: str) -> None:
        if not self.cancelled():
            self.app.call_from_thread(self.log.write, text)

    # ---- 流式头部/正文 ----

    def reset_header(self) -> None:
        self.throttler.reset()
        self.stream_active = False
        self.app.call_from_thread(self.app._hide_ai_stream)

    def refresh_stream(self, force: bool = False) -> None:
        if self.cancelled() or not self.throttler.buffer:
            return
        if not self.stream_active:
            self.app.call_from_thread(self.app._show_ai_stream)
            self.stream_active = True
        if force or self.throttler.due():
            self.throttler.mark_refreshed()
            self.app.call_from_thread(self.app._update_ai_stream, self.throttler.buffer)

    # ---- 回调（对应原闭包）----

    def on_message_end(self, segment) -> None:
        if not isinstance(segment, str):
            segment = commands.content_to_text(segment)
        if self.cancelled() or not segment.strip():
            return
        self.refresh_stream(force=True)
        self.app.call_from_thread(
            self.app._finalize_ai_stream, self.log, segment, self.start_mode
        )
        self.throttler.reset()
        self.stream_active = False

    def on_message_delta(self, delta) -> None:
        if self.cancelled():
            if not self.cancel_notified:
                self.on_cancelled()
            return
        if not isinstance(delta, str):
            return
        self.throttler.append(delta)
        self.refresh_stream()

    def on_subagent(self, name: str, status: str, depth: int) -> None:
        indent = max(0, depth - 1)
        prefix = "  " * indent
        self.write_line(f"{prefix}[yellow]▌ [{name}] {status}[/yellow]")

    def on_tool_call(self, name: str, args: str, err: bool, output: str | None, depth: int) -> None:
        self.write_line(format_tool_call(name, args, error=err, output=output, indent=depth))
        if name == "write_todos" and not self.cancelled():
            self.app.call_from_thread(self.app._refresh_todos_panel)

    def on_status(self, text: str) -> None:
        self.write_line(f"[i][dim]… {text}[/dim][/i]")

    def on_cancelled(self) -> None:
        self.cancel_notified = True
        self.stream_active = False
        self.app.call_from_thread(self.app._hide_ai_stream)
        self.write_line("[i][dim]（已取消）[/dim][/i]")

    def handle_interrupts(self, interrupts):
        filtered = streaming.filter_pending_interrupts(
            interrupts,
            self.app._resolved_hitl.get(self.app.thread_id, set()),
        )
        if not filtered:
            return None
        self.app._pending_hitl_keys = {
            streaming.interrupt_action_key(action)
            for interrupt in filtered
            for action in (getattr(interrupt, "value", None) or {}).get("action_requests", [])
        }

        def ask_action(inv):
            return self.app.call_from_thread(self.app._wait_modal_dismiss, inv)

        return streaming.collect_interrupt_decisions(
            filtered,
            ask_action,
            permission_state=self.app.permission_state,
            on_always_approve=lambda name: self.app.call_from_thread(
                self.log.write, f"[b]已设置 {name} = allow（已写入 javis.json）[/b]"
            ),
        )

    def on_turn_incomplete(self) -> None:
        self.app.call_from_thread(self.app._on_turn_incomplete, self.app.thread_id)

    def callbacks(self) -> dict:
        return {
            "on_subagent": self.on_subagent,
            "on_tool_call": self.on_tool_call,
            "on_message_delta": self.on_message_delta,
            "on_message_end": self.on_message_end,
            "on_status": self.on_status,
        }

    # ---- 主流程 ----

    def run(self) -> None:
        """在流式 worker 线程内驱动本轮（含异常兜底与收尾）。"""
        self.worker = get_current_worker()
        ok = False
        try:
            ok = streaming.run_agent_turn(
                self.app.agent,
                self.app.thread_id,
                self.user_input,
                checkpoint_id=self.checkpoint_id,
                handle_interrupts=self.handle_interrupts,
                callbacks=self.callbacks(),
                is_cancelled=self.cancelled,
                on_fallback_message=lambda text: self.app.call_from_thread(
                    self.app._finalize_ai_stream,
                    self.log,
                    text or self.throttler.buffer,
                    self.start_mode,
                ),
                on_stream_start=self.reset_header,
                on_cancelled=self.on_cancelled,
                on_turn_incomplete=self.on_turn_incomplete,
                permission_state=self.app.permission_state,
                project_root=self.app._workspace_root(),
                max_steps=int(getattr(self.app.config, "execution_max_steps", 200)),
            )
        except Exception as exc:  # noqa: BLE001
            self.reset_header()
            self.write_line(f"[bold red]错误[/bold red] {streaming.format_agent_error(exc)}")
            ok = False
        finally:
            elapsed = time() - self.started
            model = getattr(self.app.config, "model_id", "") or "model"
            self.app.call_from_thread(self.app._hide_ai_stream)
            self.app.call_from_thread(self.app._hide_spinner)
            if self.cancelled() and not self.cancel_notified:
                self.write_line("[i][dim]（已取消）[/dim][/i]")
            elif not ok and not self.cancelled():
                self.write_line("[i][dim]（已放弃本轮）[/dim][/i]")
            elif ok:
                self.write_line(f"[dim]▌ {model} ({elapsed:.1f}s)[/dim]")
            self.app.call_from_thread(self.app._refresh_todos_panel)
            self.write_line("")
