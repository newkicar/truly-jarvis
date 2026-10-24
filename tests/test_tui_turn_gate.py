"""tui-ux7 #02: 回合串行化门 + 排队（收尾期新消息排队，不并发）。

时序说明：不依赖固定 sleep 对齐 drain 窗口（跨机负载波动会假 RED），
一律「轮询实际效应」：门持有 / 排队 / 重投递 / 门释放都是可观测状态。
drain 窗口做得足够宽（8 × 0.15s ≈ 1.2s），取消发生在流启动后 ~0.2s。
"""

import asyncio
import time

import pytest
from unittest.mock import patch

from src import commands
from src.permissions import yolo_on
from src.tui import JarvisApp
from src.tui_log import CopyableRichLog
from tests.test_tui import _FakeMsg, _FakeStream, FakeAgent, _type_and_enter


class ConcurrencyAgent(FakeAgent):
    """带 inflight/max_overlap 计数的慢流：每次 stream 为 8 × sleep(0.15)。"""

    def stream_events(self, *args, **kwargs):
        agent = self
        self._calls += 1

        class S(_FakeStream):
            interrupted = False
            interrupts = None
            output = None

            def __init__(self):
                self._items = [("messages", _FakeMsg(f"seg{i}")) for i in range(8)]

            def interleave(self, *kinds):
                try:
                    for item in self._items:
                        time.sleep(0.15)
                        yield item
                finally:
                    agent.inflight -= 1

        self.inflight += 1
        self.max_overlap = max(self.max_overlap, self.inflight)
        return S()

    def __init__(self):
        super().__init__(reply="")
        self.inflight = 0
        self.max_overlap = 0


def _joined(log) -> str:
    return "".join(l.text for l in log.lines)


async def _poll(pilot, predicate, timeout: float = 10.0, msg: str = ""):
    """轮询 UI 线程条件（drain 窗口宽于 1.2s，固定 sleep 在对齐上不可靠）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause()
        await asyncio.sleep(0.05)
    raise AssertionError(f"轮询超时（{timeout:.1f}s）: {msg or predicate}")


def _queued(app, tid: str) -> list:
    return [x for t, x in app._queued_messages if t == tid]


@pytest.mark.asyncio
async def test_queue_serializes_turns_during_drain():
    """收尾期间发第二条 → 排队不抢跑；门释放后 FIFO 自动重投递；全程 max_overlap == 1。"""
    app = JarvisApp(None, ConcurrencyAgent(), {"default": "ask", "tools": {}})
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        await asyncio.sleep(0.2)
        app.action_cancel()  # tui-ux15：Esc#1 prime 取消
        app.action_cancel()  # Esc#2 实际取消（drain 收尾）
        await pilot.pause()
        await _type_and_enter(pilot, "第二条")
        # 此刻门必须仍被持有（drain 未结束），第二条只能排队
        assert app.thread_id in app._turn_gate_threads, "第二条入口时门已释放"
        assert _queued(app, app.thread_id) == ["第二条"], "第二条未入 FIFO 队列"
        assert agent._calls == 1, "第二条抢跑"
        # 门释放（drain 完成）→ FIFO 重投递
        await _poll(pilot, lambda: agent._calls == 2, msg="门释放后未重投递")
        await pilot.pause()
        assert agent.max_overlap == 1, "出现双 graph 并发（max_overlap=%d）" % agent.max_overlap
        log = pilot.app.query_one(CopyableRichLog)
        joined = _joined(log)
        assert joined.index("第一条") < joined.index("第二条")


@pytest.mark.asyncio
async def test_double_esc_during_drain_no_implicit_undo():
    """收尾中连按两次 Esc 不触发隐式撤回（guard：撤回不排队、不能隔轮回放）。"""
    app = JarvisApp(None, ConcurrencyAgent(), {"default": "ask", "tools": {}})
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        await asyncio.sleep(0.2)
        app.action_cancel()   # tui-ux15：Esc#1 prime 取消（worker 活跃）
        app.action_cancel()   # Esc#2 实际取消（worker pop；取消体设撤回 prime）
        app.action_cancel()   # Esc#3 门占用 → 撤回被拒，prime 保留
        await pilot.pause()
        # drain 结束后也无迟到的撤回（撤回只可能由 action_cancel 空闲路径触发；
        # prime 保留但无第四次按下 → 不产生撤回）
        await _poll(pilot, lambda: not app._turn_gate_threads, msg="门未释放")
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        assert "正在撤回" not in _joined(log)


@pytest.mark.asyncio
async def test_new_session_drops_queued_message():
    """收尾期间入队的消息，会话切换后作废（不重投递到新会话）。"""
    app = JarvisApp(None, ConcurrencyAgent(), {"default": "ask", "tools": {}})
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        await asyncio.sleep(0.2)
        app.action_cancel()  # tui-ux15：Esc#1 prime 取消
        app.action_cancel()  # Esc#2 实际取消（drain 收尾）
        await pilot.pause()
        await _type_and_enter(pilot, "第二条")
        assert app.thread_id in app._turn_gate_threads, "第二条入口时门已释放"
        old_tid = app.thread_id
        assert _queued(app, old_tid) == ["第二条"], "第二条未入 FIFO 队列"
        app.action_new_session()
        # 旧 thread 的门在旧 TurnPresenter finally 释放 → 排队消息作废
        await _poll(pilot, lambda: old_tid not in app._turn_gate_threads, msg="旧 thread 门未释放")
        await pilot.pause()
        assert agent._calls == 1, "旧 thread 排队消息被重投递"

def _yolo_state(tid: str) -> dict:
    state = {"default": "ask", "tools": {}, "yolo_threads": set()}
    yolo_on(state, tid)
    return state


@pytest.mark.asyncio
async def test_switch_session_non_yolo_cancels_worker():
    """tui-ux14 #03: 非 YOLO 切会话 → 旧回合 worker 被取消（既有语义回归守卫）。"""
    app = JarvisApp(None, ConcurrencyAgent(), {"default": "ask", "tools": {}}, thread_id="treg")
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        w = app._turn_workers.get("treg")
        assert w is not None and not w.is_finished, "回合 worker 未按 thread 键登记"
        app.action_new_session()
        await _poll(pilot, lambda: w.is_finished, msg="非 YOLO 切会话后 worker 未取消结束")


@pytest.mark.asyncio
async def test_switch_session_yolo_keeps_background_worker():
    """tui-ux14 #03: YOLO 切会话 → 回合 worker 后台续跑（不取消、不 finalize）。"""
    app = JarvisApp(None, ConcurrencyAgent(), _yolo_state("tyolo"), thread_id="tyolo")
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        w = app._turn_workers.get("tyolo")
        assert w is not None and not w.is_finished, "YOLO 回合 worker 未登记"
        with patch.object(commands, "finalize_turn") as fin:
            app.action_new_session()
            fin.assert_not_called()
        assert "tyolo" in app._bg_turns, "YOLO 会话未登记后台续跑"
        await _poll(pilot, lambda: w.is_finished, msg="YOLO 后台 worker 未自然结束")
        assert not w.is_cancelled, "YOLO 后台 worker 被取消"
        await _poll(pilot, lambda: "tyolo" not in app._bg_turns, msg="门释放后 bg 标记未清")


@pytest.mark.asyncio
async def test_yolo_background_gate_release_keeps_queue():
    """tui-ux14 #03: YOLO drain 期排队 + 切走 → 门释放时静默保留队列（不作废不 notify）。"""
    app = JarvisApp(None, ConcurrencyAgent(), _yolo_state("tyolo"), thread_id="tyolo")
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        await asyncio.sleep(0.2)
        app.action_cancel()  # tui-ux15：Esc#1 prime 取消
        app.action_cancel()  # Esc#2 实际取消（drain 收尾）
        await pilot.pause()
        await _type_and_enter(pilot, "第二条")
        assert "tyolo" in app._turn_gate_threads, "第二条入口时门已释放"
        assert _queued(app, "tyolo") == ["第二条"], "第二条未入 FIFO 队列"
        app.action_new_session()
        await _poll(
            pilot,
            lambda: "tyolo" not in app._turn_gate_threads and "tyolo" not in app._bg_turns,
            msg="门/bg 标记未释放",
        )
        await pilot.pause()
        assert _queued(app, "tyolo") == ["第二条"], "门释放时排队消息被作废"
        assert agent._calls == 1, "排队消息在新会话被重投递"


@pytest.mark.asyncio
async def test_switch_back_to_yolo_session_redelivers_queue():
    """tui-ux14 #03: 切回 YOLO 会话（门已释放）→ 重投队首，排空队列。"""
    app = JarvisApp(None, ConcurrencyAgent(), _yolo_state("tyolo"), thread_id="tyolo")
    agent = app.agent
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "第一条")
        await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
        await asyncio.sleep(0.2)
        app.action_cancel()  # tui-ux15：Esc#1 prime 取消
        app.action_cancel()  # Esc#2 实际取消（drain 收尾）
        await pilot.pause()
        await _type_and_enter(pilot, "第二条")
        app.action_new_session()
        await _poll(
            pilot,
            lambda: "tyolo" not in app._turn_gate_threads and "tyolo" not in app._bg_turns,
            msg="门未释放",
        )
        app._switch_session("tyolo")
        await _poll(pilot, lambda: agent._calls >= 2, msg="切回后排队消息未重投")
        await pilot.pause()
        assert _queued(app, "tyolo") == [], "排队消息未消费"