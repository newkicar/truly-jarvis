"""tui-ux16 sticky scroll 单测（CopyableRichLog 贴底自动跟随 + 跳转提示，对标 codex）。

App 启动方式沿用 tests/test_tui.py；不用 tmp_path/tempfile；纯内存。
"""
import pytest
from textual.containers import Container
from textual.widgets import Button, Static

from src.tui import JarvisApp, JarvisTextArea
from src.tui_log import CopyableRichLog
from tests.test_tui import FakeAgent


def _new_app() -> JarvisApp:
    return JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})


async def _fill(pilot, log: CopyableRichLog, lines: int = 40) -> None:
    """写 `lines` 行进日志（贴底时每次自动跟随，pending 保持 0）。"""
    for i in range(lines):
        log.write(f"line {i}")
        await pilot.pause()


def _hint(pilot) -> Button:
    return pilot.app.query_one("#jump_hint", Button)


@pytest.mark.asyncio
async def test_stream_shrink_still_follows():
    """tui-ux16r2 H1: ai_stream sibling appearing resizes the log;
    a user stuck at the bottom must keep following in real time."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        assert log.scroll_offset.y == log.max_scroll_y
        stream = pilot.app.query_one("#ai_stream", Static)
        stream.add_class("-active")
        await pilot.pause()
        for i in range(3):
            log.write(f"w{i}")
            await pilot.pause()
        assert log.scroll_offset.y == log.max_scroll_y
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_bottom_write_follows_no_hint():
    """贴底时写入自动跟随：无 pending、无 hint。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 5)
        log.write("hello")
        await pilot.pause()
        assert log.scroll_offset.y == log.max_scroll_y
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_scrolled_up_write_no_jump_counts_pending():
    """上翻后写入停跳：位置不动、pending +1、hint 可见（固定文案 Back to bottom）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("msg1")
        await pilot.pause()
        assert log.scroll_offset.y == 0
        assert log._pending_msgs == 1  # noqa: SLF001
        hint = _hint(pilot)
        assert hint.has_class("-visible")
        assert hint.label.plain == "Back to bottom"


@pytest.mark.asyncio
async def test_pending_accumulates_label_updates():
    """上翻时连续 3 次写入 pending 累计为 3，hint 文案同步。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        for i in range(3):
            log.write(f"m{i}")
            await pilot.pause()
        assert log._pending_msgs == 3  # noqa: SLF001
        assert _hint(pilot).label.plain == "Back to bottom"


@pytest.mark.asyncio
async def test_blank_write_not_counted():
    """空白写入不计入 pending。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("")
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_click_hint_jumps_and_resumes_follow():
    """点击 hint：跳到底部、清 pending、隐 hint；后续写入恢复自动跟随。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m0")
        await pilot.pause()
        assert log._pending_msgs == 1 and _hint(pilot).has_class("-visible")  # noqa: SLF001
        # pilot 合成鼠标事件不置 grabber，Button._on_click 不按压（Textual 测试惯用法：.press()）
        _hint(pilot).press()
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")
        assert log.scroll_offset.y == log.max_scroll_y
        log.write("m1")
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_real_mouse_click_hint_jumps_to_bottom():
    """真实鼠标路径（pilot.click -> MouseDown/MouseUp/Click -> Button._on_click）
    必须触发跳转。回归锚点：Textual 8.2.8 Button._on_click 内有
    `if not self.has_class("-active"): self.press()`——hint 的「可见」态若复用
    Button 内部按压态类名 `-active`，真实点击会被吞掉（本 bug 根因）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m0")
        await pilot.pause()
        hint = _hint(pilot)
        assert hint.has_class("-visible")
        ok = await pilot.click(hint)
        assert ok, "hint 未在指针下（z-order/几何错误）"
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001
        assert log.scroll_offset.y == log.max_scroll_y


@pytest.mark.asyncio
async def test_manual_scroll_to_bottom_clears_hint():
    """手动滚到底（程序化）：清 pending、隐 hint。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m0")
        await pilot.pause()
        assert log._pending_msgs == 1  # noqa: SLF001
        # RichLog.scroll_end 默认 animate=True/duration=1.0（动画非瞬时），须 animate=False 同步跳底
        log.scroll_end(animate=False, immediate=True, x_axis=False)
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_clear_resets_pending_and_hint():
    """日志清空：复位 pending、隐 hint。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m0")
        await pilot.pause()
        assert log._pending_msgs == 1  # noqa: SLF001
        log.clear()
        await pilot.pause()
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_scrolled_up_shrink_no_yank():
    """tui-ux16r2 H1: scrolled up, ai_stream appearing must NOT yank
    the user down; pending counted, hint visible; pressing hint jumps back."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        stream = pilot.app.query_one("#ai_stream", Static)
        stream.add_class("-active")
        await pilot.pause()
        assert log.scroll_offset.y == 0
        log.write("m")
        await pilot.pause()
        assert log.scroll_offset.y == 0
        assert log._pending_msgs == 1  # noqa: SLF001
        assert _hint(pilot).has_class("-visible")
        _hint(pilot).press()
        await pilot.pause()
        assert log.scroll_offset.y == log.max_scroll_y
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_hint_docked_at_log_bottom():
    """tui-ux19r2: active hint docks at the bottom of #messages_box as a
    narrow left-anchored pill (width: auto) below the log viewport; a band
    row no longer intercepts the full width (only the pill is clickable)."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        box = pilot.app.query_one("#messages_box", Container)
        hint = _hint(pilot)
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m")
        await pilot.pause()
        assert hint.has_class("-visible")
        hint_region = hint.region
        box_region = box.region
        log_region = log.region
        assert hint_region.width < box_region.width  # narrow pill, not full width
        assert hint_region.y + hint_region.height == box_region.y + box_region.height
        assert log_region.y + log_region.height <= hint_region.y


@pytest.mark.asyncio
async def test_hint_stick_recovery():
    """tui-ux16r2 H1: at bottom with ai_stream visible, hide it again;
    follow state recovers: no pending, hint off, still at bottom."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log)
        stream = pilot.app.query_one("#ai_stream", Static)
        stream.add_class("-active")
        await pilot.pause()
        for i in range(3):
            log.write(f"m{i}")
            await pilot.pause()
        stream.remove_class("-active")
        await pilot.pause()
        assert log.scroll_offset.y == log.max_scroll_y
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


# ---------------------------------------------------------------------------
# tui-ux17: 点击日志区聚焦 + 原生翻页键 + y/Esc 阅读态门控
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_log_focuses_it():
    """tui-ux17: 点击日志区使其获得焦点（原生翻页键生效的前置条件）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 20)
        await pilot.click(log, offset=(40, 5))
        assert pilot.app.focused is log


@pytest.mark.asyncio
async def test_pagedown_pages_after_focus():
    """tui-ux17: 聚焦后 PgDn 原生翻一页下（先手动滚到顶制造距离）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        log.scroll_y = 0
        await pilot.pause()
        await pilot.click(log, offset=(40, 5))
        await pilot.press("pagedown")
        await pilot.pause()
        assert log.scroll_offset.y > 0


@pytest.mark.asyncio
async def test_end_key_jumps_to_bottom_clears_pending():
    """tui-ux17: 聚焦后 End 键跳底（带默认动画，有界等待循环），恢复贴底、
    清 pending、隐藏 hint。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        log.scroll_y = 0
        await pilot.pause()
        log.write("x")
        await pilot.pause()
        assert log._pending_msgs == 1  # noqa: SLF001
        await pilot.click(log, offset=(40, 5))
        await pilot.press("end")
        for _ in range(100):
            await pilot.pause()
            if log.is_vertical_scroll_end:
                break
        assert log.is_vertical_scroll_end
        assert log._pending_msgs == 0  # noqa: SLF001
        assert not _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_pageup_shows_hint_after_focus():
    """tui-ux17: 聚焦后 PgUp 翻一页上，离开底部 →「Back to bottom」hint 常显。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        await pilot.click(log, offset=(40, 5))
        await pilot.press("pageup")
        await pilot.pause()
        assert log.scroll_offset.y < log.max_scroll_y
        assert _hint(pilot).has_class("-visible")


@pytest.mark.asyncio
async def test_home_key_jumps_to_top():
    """tui-ux17: 聚焦后 Home 键跳顶（带默认动画，有界等待循环）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        await pilot.click(log, offset=(40, 5))
        await pilot.press("home")
        for _ in range(100):
            await pilot.pause()
            if log.scroll_offset.y == 0:
                break
        assert log.scroll_offset.y == 0


@pytest.mark.asyncio
async def test_y_on_focused_log_notifies_not_silent_copy():
    """tui-ux17: 焦点在日志区且无选区时，y 弹侧边栏提示，不再静默复制 thread_id。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 20)
        await pilot.click(log, offset=(40, 5))
        assert pilot.app.focused is log
        assert pilot.app.thread_id  # 无门控时走静默复制分支的前置条件
        calls: list = []
        pilot.app.notify = lambda *a, **k: calls.append(a)  # type: ignore[method-assign]
        pilot.app.action_copy_session_or_selection()
        texts = " ".join(str(x) for tup in calls for x in tup)
        assert "侧边栏" in texts
        assert "已复制" not in texts


@pytest.mark.asyncio
async def test_esc_on_focused_log_exits_reading_mode_only():
    """tui-ux17: 焦点在日志区时首个 Esc 仅退出阅读态（焦点回 #input），
    不进三段取消/撤回流程（_esc_phase 保持 none）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 20)
        await pilot.click(log, offset=(40, 5))
        assert pilot.app.focused is log
        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.focused is pilot.app.query_one("#input", JarvisTextArea)
        assert pilot.app._esc_phase == "none"  # noqa: SLF001

# ---------------------------------------------------------------------------
# tui-ux19r2: clickable tool entries - band click interception + pending
# registration + max_lines fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_band_click_outside_pill_does_not_jump():
    """tui-ux19r2: with hint visible (scrolled up), a click on the band row
    at a column beyond the pill width must not trigger the jump (pre-fix
    the full-width band Button intercepted every column of the band row)."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        box = pilot.app.query_one("#messages_box", Container)
        await _fill(pilot, log, 40)
        log.scroll_y = 0
        await pilot.pause()
        log.write_tool_entry("tool line c", "expanded detail e")
        await pilot.pause()
        entry = log._tool_entries[-1]  # noqa: SLF001
        assert entry["active"] is False
        hint = _hint(pilot)
        assert hint.has_class("-visible")
        # 屏幕 80 列 = 侧边栏 + box：pilot offset 是 box 相对坐标，绝对坐标必须落回屏内。
        # 取 band 行最右列——既在屏内，又必在窄 pill（width:auto）之外。
        col = box.region.width - 1
        assert col >= hint.region.x - box.region.x + hint.region.width
        band_y_rel = hint.region.y - box.region.y + 1
        ok = await pilot.click(box, offset=(col, band_y_rel))
        assert ok  # 点击落在 band 行（box 内），而非 box 下方其他部件
        await pilot.pause()
        assert entry["active"] is False
        assert log.scroll_offset.y < log.max_scroll_y  # did not jump to bottom


@pytest.mark.asyncio
async def test_click_marker_line_toggles_entry():
    """Guard: clicking the marker line inside the log toggles the tool
    entry (expanded <-> collapsed); green pre- and post-fix. Fills past
    the viewport so the click lands in a scrolled state - the hit-test
    arithmetic (content_row = scroll_offset.y + event.y) must hold with
    a non-zero scroll offset."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await _fill(pilot, log, 40)
        log.write_tool_entry("tool line c", "expanded detail e")
        log.scroll_end(animate=False, immediate=True, x_axis=False)
        await pilot.pause()
        assert log.max_scroll_y > 0
        assert int(log.scroll_offset.y) == int(log.max_scroll_y)
        entry = log._tool_entries[-1]  # noqa: SLF001
        assert entry["active"] is False
        marker_y_rel = entry["end"] - 1 - int(log.scroll_offset.y)
        assert marker_y_rel >= 0
        ok = await pilot.click(log, offset=(1, marker_y_rel))
        assert ok
        await pilot.pause()
        assert log._tool_entries[-1]["active"] is True


@pytest.mark.asyncio
async def test_tool_entry_before_show_is_pending_then_materializes():
    """tui-ux19r2: write_tool_entry before on_show (layout not settled,
    _size_known=False) registers a pending entry instead of dropping it
    (pre-fix: not registered at all -> clicking the detail line did
    nothing, the reported bug). on_show materializes the dual variants
    in place; the toggle then works."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log._size_known = False  # noqa: SLF001 force the pre-layout path
        log.write_tool_entry("early tool line", "early detail")
        entries = log._tool_entries  # noqa: SLF001
        assert len(entries) == 1
        entry = entries[0]
        assert entry["strips"] is None
        collapsed, expanded = entry["pending"]
        assert "early tool line" in collapsed
        assert "early detail" in expanded
        log.on_show(None)  # noqa: SLF001 materialize
        await pilot.pause()
        entry = log._tool_entries[-1]  # noqa: SLF001
        assert entry["strips"] is not None
        assert entry["pending"] is None
        log.scroll_end(animate=False, immediate=True, x_axis=False)
        await pilot.pause()
        marker_y_rel = entry["end"] - 1 - int(log.scroll_offset.y)
        ok = await pilot.click(log, offset=(1, marker_y_rel))
        assert ok
        await pilot.pause()
        assert log._tool_entries[-1]["active"] is True


@pytest.mark.asyncio
async def test_max_lines_log_keeps_plain_fallback():
    """Guard: with max_lines set (RichLog trims history), write_tool_entry
    stays a plain write and registers no clickable entry."""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log.max_lines = 5
        log.write_tool_entry("plain c", "plain e")
        await pilot.pause()
        assert log._tool_entries == []  # noqa: SLF001
        assert "plain c" in log.plain_text()


# ------------------------------------------------------------------
# #36 常驻上箭头：jump_up 落到视口严格上方最近一条用户消息
# ------------------------------------------------------------------

def _up(pilot) -> Button:
    return pilot.app.query_one("#jump_up", Button)


@pytest.mark.asyncio
async def test_jump_up_button_always_visible_in_both_states():
    """#36: ↑ 常驻（无 display 门控）——贴底与上翻两态均可见。
    贴 ↓ 提示条正上方，不压日志内容区。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        up = _up(pilot)
        hint = _hint(pilot)
        # 贴底态：hint 隐藏、↑ 显示
        assert up.display
        assert not hint.has_class("-visible")
        up_region = up.region
        log_region = log.region
        assert up_region.y + up_region.height > 0
        assert log_region.y + log_region.height <= up_region.y
        # 上翻态：hint 显示，↑ 仍显示
        await _fill(pilot, log)
        log.scroll_y = 0
        await pilot.pause()
        log.write("m")
        await pilot.pause()
        assert hint.has_class("-visible")
        assert up.display
        up_region = up.region
        hint_region = hint.region
        log_region = log.region
        assert up_region.y + up_region.height <= hint_region.y
        assert log_region.y + log_region.height <= up_region.y


@pytest.mark.asyncio
async def test_jump_up_lands_on_nearest_user_message_strictly_above():
    """#36: 点 ↑ → 顶线严格在视口上方（完全在上方）最近一条用户消息顶线对齐视口顶线；
    部分可见跳过；落点后 sticky 状态机自动显 ↓ 提示。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log.write("user-A", user_anchor=True)
        await _fill(pilot, log, 40)
        log.write("user-B", user_anchor=True)
        await pilot.pause()
        a = next(it for it in log._items if it.get("user_anchor") and it["source"] == "user-A")
        b = next(it for it in log._items if it.get("user_anchor") and it["source"] == "user-B")
        assert b["start"] > a["end"]
        log.scroll_y = a["end"]  # A 完全在视口顶上方，B 远在下方
        await pilot.pause()
        ok = await pilot.click(_up(pilot))
        assert ok
        assert int(log.scroll_offset.y) == a["start"]
        assert _hint(pilot).has_class("-visible")  # sticky 状态机自动显 ↓


@pytest.mark.asyncio
async def test_jump_up_no_target_is_noop():
    """#36: 视口严格上方无用户消息 → jump_up 返回 False 且滚动位置不变。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log.write("user-only", user_anchor=True)
        await _fill(pilot, log, 40)
        await pilot.pause()
        log.scroll_y = 0
        await pilot.pause()
        assert log.jump_up() is False
        assert int(log.scroll_offset.y) == 0


@pytest.mark.asyncio
async def test_jump_up_landing_survives_reflow():
    """#36: 目标点击时求值（不缓存）——reflow 重算 start/end 后 ↑ 仍落到新坐标。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log.write("X" * 200)  # 宽 80 时 3 行
        log.write("user-A", user_anchor=True)
        await _fill(pilot, log, 30)
        log.write("user-B", user_anchor=True)
        await pilot.pause()
        a_old = next(it for it in log._items if it.get("user_anchor") and it["source"] == "user-A")
        start_old, end_old = a_old["start"], a_old["end"]
        await pilot.resize_terminal(40, 24)  # 收窄 → X*200 重折为更多行
        await pilot.pause()
        a_new = next(it for it in log._items if it.get("user_anchor") and it["source"] == "user-A")
        assert a_new["start"] != start_old  # 证明 reflow 确实挪动了坐标（非空洞断言）
        assert a_new["end"] != end_old
        log.scroll_y = a_new["end"]
        await pilot.pause()
        assert log.jump_up() is True
        assert int(log.scroll_offset.y) == a_new["start"]


@pytest.mark.asyncio
async def test_pre_layout_writes_preserve_user_anchor_through_drain():
    """#36: 预布局 write(user_anchor=True) 3 元组入队；on_show drain 还原标记；
    旧 2 元组形态兼容（user_anchor=False）；工具条目不受影响。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        log._size_known = False  # noqa: SLF001
        log.write("u-anchor", user_anchor=True)
        log.write("plain-line")
        log._pending_writes.append(("native", "legacy-native"))  # noqa: SLF001 旧 2 元组兼容
        log.write_tool_entry("tool-c", "tool-e")
        before = len(log._items)  # noqa: SLF001
        log._size_known = True  # noqa: SLF001
        log.on_show(None)  # noqa: SLF001 drain + materialize
        await pilot.pause()
        new_items = log._items[before:]  # noqa: SLF001
        assert new_items[0]["source"] == "u-anchor"
        assert new_items[0]["user_anchor"] is True
        assert new_items[1]["user_anchor"] is False
        assert new_items[2]["source"] == "legacy-native"
        assert new_items[2]["user_anchor"] is False
        assert new_items[3]["kind"] == "tool"
