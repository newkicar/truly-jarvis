"""tui-ux14 #04: TUI 插队消息缓存面板·集成层测试（Textual 8.2.8 headless）。

覆盖：门持有期入缓存不抢跑 / 面板截断+提示 / 左键撤回回填输入框 /
门释放重投队首 / 切会话重绘画+切回重投 / stale 释放整个作废。
模块层语义见 tests/test_jump_in_queue.py；本文件只验证 TUI 容器/面板/事件接线。
"""
import asyncio

import pytest
from textual.events import Click
from textual.containers import VerticalScroll

from src.tui import JarvisApp, JarvisTextArea, MessageQueueRow
from tests.test_tui import _type_and_enter
from tests.test_tui_turn_gate import ConcurrencyAgent, _poll


def _panel(app):
    return app.query_one("#message_queue", VerticalScroll)


def _panel_rows(app):
    return [c for c in _panel(app).children if isinstance(c, MessageQueueRow)]


def _click(row):
    row.on_click(
        Click(
            widget=row, x=0, y=0, delta_x=0, delta_y=0,
            button=1, shift=False, meta=False, ctrl=False,
        )
    )


async def _enter_gate(app, agent, pilot):
    """发首条消息（门持有）→ cancel（worker 收尾 finally 释门，削决定面不受影响）。"""
    await _type_and_enter(pilot, "第一条")
    await _poll(pilot, lambda: agent._calls >= 1, msg="第一条流未启动")
    await asyncio.sleep(0.2)
    app.action_cancel()  # tui-ux15 Esc 三段：#1 prime 取消（仅提醒）
    app.action_cancel()  # #2 实际取消（drain 收尾）
    await pilot.pause()


@pytest.mark.asyncio
async def test_gate_held_enqueue_no_rush():
    """"门持有期第二条消息进缓存，不启动第二轮。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _enter_gate(app, agent, pilot)
        tid = app.thread_id
        await _type_and_enter(pilot, "第二条")
        assert tid in app._turn_gate_threads
        assert app._queue.count(tid) == 1
        assert app._queued_messages == [(tid, "第二条")]
        assert agent._calls == 1, "第二条抢跑"


@pytest.mark.asyncio
async def test_panel_truncate_and_notify():
    """缓存行>40 字截断…（tooltip 全文）；入缓存途知 notify。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _enter_gate(app, agent, pilot)
        tid = app.thread_id
        await _type_and_enter(pilot, "第二条")
        assert app._queue.pop_first(tid) == "第二条"  # 先打空队列保定定性，避门释放重投乱入
        long_msg = "x" * 100
        app._queue.push(tid, "short")
        app._queue.push(tid, long_msg)
        await pilot.pause()
        notes = [n.message for n in app._notifications._notifications.values()]
        assert any("消息缓存" in m for m in notes), "入缓存提示未发出（timeout=2s，须在长轮误前断言）"
        await _poll(
            pilot,
            lambda: [r._msg_full for r in _panel_rows(app)] == ["short", long_msg],
            msg="缓存面板行未更新",
        )
        assert "-active" in _panel(app).classes
        rows = _panel_rows(app)
        assert rows[0].content.plain == "short"
        assert rows[1].content.plain == long_msg[:40] + "…"
        assert rows[1].tooltip == long_msg


@pytest.mark.asyncio
async def test_left_click_retract_refill_input():
    """左键点击缓存行 → 移出缓存 + 回填输入框（光标尾部）+ 输入框重焦 + 面板行清除。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _enter_gate(app, agent, pilot)
        tid = app.thread_id
        full = "左键撤回编辑这条再发送"
        app._queue.push(tid, full)
        await _poll(pilot, lambda: len(_panel_rows(app)) == 1, msg="缓存行未挂载")
        _click(_panel_rows(app)[0])
        assert app._queue.count(tid) == 0
        input_box = pilot.app.query_one("#input", JarvisTextArea)
        assert input_box.text == full
        assert input_box.cursor_location == (0, len(full))
        await _poll(pilot, lambda: pilot.app.focused is input_box, msg="输入框未重新聚焦")
        await _poll(pilot, lambda: not _panel_rows(app), msg="缓存面板行未清除")


@pytest.mark.asyncio
async def test_gate_release_redeliver_head():
    """worker 收尾释门 → 缓存队首自动重投启动下一轮。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _enter_gate(app, agent, pilot)
        tid = app.thread_id
        await _type_and_enter(pilot, "第二条")
        assert app._queue.count(tid) == 1
        await _poll(pilot, lambda: agent._calls == 2, msg="排队消息未重投")
        assert app._queue.count(tid) == 0
        assert app._queued_messages == []
        await _poll(pilot, lambda: not _panel_rows(app), msg="缓存面板未清除")


@pytest.mark.asyncio
async def test_session_switch_redraw_and_return_redeliver():
    """A→B 重绘画按 B（A 缓存保留）；B→A 门未持有时重投 A 队首。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}}, thread_id="A")
    async with app.run_test() as pilot:
        app._queue.push("A", "第一条")
        app._queue.push("A", "第二条")
        await _poll(
            pilot,
            lambda: [r._msg_full for r in _panel_rows(app)] == ["第一条", "第二条"],
            msg="A 缓存面板未重绘",
        )
        app._switch_session("B")
        await _poll(pilot, lambda: app.thread_id == "B")
        assert "-active" not in _panel(app).classes, "B 无缓存应隐藏面板"
        assert app._queue.count("A") == 2, "A 缓存不得因切会话作废"
        app._switch_session("A")
        await _poll(pilot, lambda: agent._calls >= 1, msg="切回 A 未重投队首")
        assert app._queue.items("A") == ["第二条"]
        await _poll(
            pilot,
            lambda: [r._msg_full for r in _panel_rows(app)] == ["第二条"],
            msg="切回 A 面板未重绘",
        )


@pytest.mark.asyncio
async def test_stale_release_clears_cache():
    """新会话 → 旧 thread 门释放走 stale 分支：缓存整个作废 + 提示，回合数不增。"""
    agent = ConcurrencyAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _enter_gate(app, agent, pilot)
        old_tid = app.thread_id
        await _type_and_enter(pilot, "第二条")
        assert app._queue.count(old_tid) == 1
        app.action_new_session()
        await _poll(pilot, lambda: old_tid not in app._turn_gate_threads, msg="旧 thread 门未释放")
        await pilot.pause()
        assert app._queue.count(old_tid) == 0, "stale 释放应 clear 旧缓存"
        assert app._queued_messages == []
        assert agent._calls == 1, "作废的缓存不得再发"
