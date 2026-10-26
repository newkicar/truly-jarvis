"""GUI runtime 装配 + 回合 worker（架构 A：进程内，与 TUI/CLI 同源装配）。

装配时序（对齐 main.py，GUI 差异点见注释）：
  config → SqliteSaver（连接持有到 app 关闭）→ build_permission_interrupts
  → build_agent（主代理 + 子代理 + 中间件栈）→ JumpInRegistry（插队缓存）
  → McpLoader（可选）→ SchedulerGate（可选，默认关）。

回合模型：GuiPresenter.start_turn 起 daemon worker 跑 run_agent_turn，
事件经 UiBridge 信号回主线程；每 thread 回合门 + FIFO 队列（turn_gate.TurnGate）。
ask_action 是可插拔的：01 兜底 = 拒绝（不执行任何 gated 工具，安全默认），
04 换内联审批卡片。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from threading import Thread
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver

from src import commands, streaming
from src.agent import build_agent
from src.config import Config
from src.jump_in_queue import JumpInRegistry
from src.permissions import build_permission_interrupts

from src.gui.events import UiBridge
from src.gui.turn_gate import TurnGate


@dataclass
class GuiRuntime:
    """GUI 装配产物（主窗口与 presenter 共享；close() 释放 checkpointer 连接）。"""

    config: Config
    agent: Any
    checkpointer: SqliteSaver
    permission_state: dict
    registry: JumpInRegistry
    mcp_tool_count: int = 0
    model_label: str = ""
    cancel_reasons: dict = field(default_factory=dict)
    saver_ctx: Any = None
    gate: "SchedulerGate" = None

    def close(self) -> None:
        if self.saver_ctx is not None:
            self.saver_ctx.__exit__(None, None, None)
            self.saver_ctx = None
        # SqliteSaver 无 close()；无 saver_ctx（测试直接构造）时幂等无操作


def build_runtime(
    config: Config,
    *,
    model: Any | None = None,
    mcp_tools: list | None = None,
    enable_mcp: bool = False,
    enable_scheduled: bool = False,
    label: str | None = None,
) -> tuple[GuiRuntime, "SchedulerGate"]:
    """装配 runtime + 可选 scheduler 门。enable_scheduled=False 时 scheduler 不启动（遗留 d）。"""
    config.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)

    if enable_mcp and mcp_tools is None:
        from src.mcps import load_mcp_tools

        mcp_tools = load_mcp_tools(config.mcps)

    # checkpointer 连接生命周期 = app 生命周期：from_conn_string 是 contextmanager，
    # 手动 __enter__ 持有（不在 build 内 with——否则返回即关连接），close() 时 __exit__。
    saver_ctx = SqliteSaver.from_conn_string(str(config.checkpoint_db))
    checkpointer = saver_ctx.__enter__()
    checkpointer.setup()
    try:
        _, permission_state = build_permission_interrupts(
            config.permissions,
            hooks=config.hooks,
            project_root=config.project_root,
        )
        registry = JumpInRegistry()
        agent = build_agent(
            config,
            model=model,
            checkpointer=checkpointer,
            permission_state=permission_state,
            mcp_tools=mcp_tools,
            jump_in_registry=registry,
        )
    except Exception:
        saver_ctx.__exit__(None, None, None)
        raise
    runtime = GuiRuntime(
        config=config,
        agent=agent,
        checkpointer=checkpointer,
        permission_state=permission_state,
        registry=registry,
        mcp_tool_count=len(mcp_tools or []),
        model_label=label or config.model_id,
        saver_ctx=saver_ctx,
    )
    gate = SchedulerGate(runtime, enabled=enable_scheduled)
    runtime.gate = gate
    return runtime, gate


def build_runtime_for_config(home, *, model=None, enable_mcp=False, enable_scheduled=False) -> GuiRuntime:
    """测试 / 冒烟入口：home（含 jarvis.json + .env）→ runtime。"""
    from pathlib import Path as _Path

    from src.config import load_config

    config = load_config(project_root=_Path(home))
    rt, _gate = build_runtime(
        config, model=model, enable_mcp=enable_mcp, enable_scheduled=enable_scheduled
    )
    return rt


class SchedulerGate:
    """定时任务可选门（遗留 d）：enabled=False 时不启动 scheduler，单 scheduler 约束。"""

    def __init__(self, runtime: GuiRuntime, enabled: bool = False) -> None:
        self._sched = None
        self._runtime = runtime
        if enabled:
            from src import scheduler

            self._sched = scheduler.make_scheduler(runtime.agent, runtime.config)
            self._sched.start()

    @property
    def enabled(self) -> bool:
        return self._sched is not None

    def jobs(self) -> list:
        return self._sched.get_jobs() if self._sched else []

    def reload(self) -> int:
        if self._sched is None:
            return 0
        return self._sched.reload_schedules()

    def shutdown(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None


# ---------------------------------------------------------------- 回合 worker


class GuiPresenter:
    """worker 线程宿主：start_turn 起 worker 跑 run_agent_turn，事件走 UiBridge。

    ask_action（HITL 取卡）可替换：set_ask_action(fn)；01 兜底 = 拒绝 + 提示。
    """

    def __init__(self, runtime: GuiRuntime, bridge: UiBridge) -> None:
        self.runtime = runtime
        self.bridge = bridge
        self.gate = TurnGate()
        self._ask_action: Callable[[Any, str], dict | None] | None = None
        self._turns: dict[str, Any] = {}

    # ---- HITL 取卡（01 兜底：拒绝，安全默认；04 换审批卡片）
    def set_ask_action(self, fn: Callable[[Any, str], dict | None]) -> None:
        self._ask_action = fn

    def _default_ask(self, inv: Any, tid: str) -> dict | None:
        self.bridge.notify.emit(
            f"工具 {inv.name} 需审批：GUI 审批卡片尚未启用（工单 04），本轮已拒绝执行。"
        )
        return {"decision": "reject"}

    # ---- 提交
    def start_turn(
        self,
        tid: str,
        user_text: str,
        *,
        user_input: Any | None = None,
        user_input_fallback: str | None = None,
    ) -> str:
        """入回合门。返回 'started' / 'queued'。queued 时该 thread 提示「已排队 N」。

        FIFO 重投：worker 结束时 gate.finish 出队下一条并再走 start_turn（重新入门）。
        """
        verdict = self.gate.try_start(tid, user_text)
        if verdict == "queued":
            n = self.gate.queued_count(tid)
            self.bridge.notify.emit(f"该会话回合进行中，消息已排队（当前第 {n} 条）。")
            return verdict
        self._launch(tid, user_text, user_input, user_input_fallback)
        return verdict

    def _launch(self, tid: str, user_text: str, user_input: Any | None, user_input_fallback: str | None) -> None:
        th = Thread(
            target=self._turn_worker,
            args=(tid, user_text, user_input, user_input_fallback),
            daemon=True,
            name=f"jarvis-gui-turn-{tid[:10]}",
        )
        self._turns[tid] = th
        th.start()

    def cancel(self, tid: str) -> None:
        self.gate.request_cancel(tid)
        self.bridge.status.emit(tid, "已取消，正在收尾（当前步骤结束后停止）")

    # ---- worker（worker 线程；只 emit 信号 + 调 runtime，不碰 widget）
    def _turn_worker(
        self,
        tid: str,
        user_text: str,
        user_input: Any | None,
        user_input_fallback: str | None,
    ) -> None:
        rt = self.runtime
        b = self.bridge
        t0 = time.monotonic()
        b.turn_started.emit(tid)
        try:
            ok = streaming.run_agent_turn(
                rt.agent,
                tid,
                user_input if user_input is not None else user_text,
                handle_interrupts=lambda its: streaming.collect_interrupt_decisions(
                    its,
                    lambda inv: (self._ask_action or self._default_ask)(inv, tid),
                    permission_state=rt.permission_state,
                    on_always_approve=lambda n: b.notify.emit(
                        f"已永久放行 {n}（写入 jarvis.json，以后自动放行）"
                    ),
                ),
                callbacks={
                    "on_message_delta": lambda d: b.message_delta.emit(tid, d),
                    "on_message_end": lambda t: b.message_end.emit(tid, t),
                    "on_tool_call": lambda n, a, e, o=None, depth=0: b.tool_call.emit(
                        tid, n, a, e, o or "", depth
                    ),
                    "on_subagent": lambda n, s, depth=0: b.subagent.emit(tid, n, s, depth),
                    "on_status": lambda s: b.status.emit(tid, s),
                },
                on_fallback_message=lambda t: b.fallback.emit(tid, t),
                is_cancelled=lambda: self.gate.is_cancelled(tid),
                permission_state=rt.permission_state,
                project_root=rt.config.project_root,
                max_steps=rt.config.execution_max_steps,
                model_image_input=rt.config.model_image_input,
                user_input_fallback=user_input_fallback,
            )
            self.bridge.turn_done.emit(tid, bool(ok))
            self.bridge.notify.emit(f"回合{'完成' if ok else '放弃/取消'}（{time.monotonic() - t0:.1f}s）")
        except Exception as exc:  # noqa: BLE001 — worker 边界兜底，错误回主线程展示
            b.turn_done.emit(tid, False)
            b.notify.emit(streaming.format_agent_error(exc))
        finally:
            self._turns.pop(tid, None)
            b.refresh_sessions.emit()
            # FIFO 重投：出队下一条排队消息，重新入门起新回合（工单 03）
            nxt = self.gate.finish(tid)
            if nxt is not None:
                self.start_turn(tid, nxt)

    # ---- 回放（时间旅行，ticket 09）
    def start_replay(self, tid: str, checkpoint_id: str) -> None:
        th = Thread(
            target=self._replay_worker,
            args=(tid, checkpoint_id),
            daemon=True,
            name=f"jarvis-gui-replay-{tid[:10]}",
        )
        th.start()

    def _replay_worker(self, tid: str, checkpoint_id: str) -> None:
        rt = self.runtime
        b = self.bridge
        b.status.emit(tid, f"从快照 {checkpoint_id[:10]} 重放…")
        try:
            streaming.run_agent_turn(
                rt.agent,
                tid,
                None,
                checkpoint_id=checkpoint_id,
                handle_interrupts=lambda its: streaming.collect_interrupt_decisions(
                    its,
                    lambda inv: (self._ask_action or self._default_ask)(inv, tid),
                    permission_state=rt.permission_state,
                ),
                callbacks={
                    "on_message_delta": lambda d: b.message_delta.emit(tid, d),
                    "on_message_end": lambda t: b.message_end.emit(tid, t),
                    "on_tool_call": lambda n, a, e, o=None, depth=0: b.tool_call.emit(
                        tid, n, a, e, o or "", depth
                    ),
                    "on_subagent": lambda n, s, depth=0: b.subagent.emit(tid, n, s, depth),
                    "on_status": lambda s: b.status.emit(tid, s),
                },
                on_fallback_message=lambda t: b.fallback.emit(tid, t),
                permission_state=rt.permission_state,
                project_root=rt.config.project_root,
                max_steps=rt.config.execution_max_steps,
            )
        except Exception as exc:  # noqa: BLE001
            b.notify.emit(streaming.format_agent_error(exc))
        finally:
            b.refresh_sessions.emit()

    # ---- 命令 worker（undo/compact/snapshot 等消息层操作，ticket 08/09）
    def run_command(self, fn: Callable[[], str], tid: str) -> None:
        th = Thread(target=self._command_worker, args=(fn, tid), daemon=True)
        th.start()

    def _command_worker(self, fn: Callable[[], str], tid: str) -> None:
        b = self.bridge
        try:
            result = fn()
            b.notify.emit(result)
        except Exception as exc:  # noqa: BLE001
            b.notify.emit(f"命令失败: {exc}")
        finally:
            b.refresh_sessions.emit()

    # ---- 会话（ticket 05）
    def new_session_id(self) -> str:
        return f"session-{uuid.uuid4().hex[:8]}"

    def session_ids(self) -> list[str]:
        return commands.session_thread_ids(self.runtime.agent)
