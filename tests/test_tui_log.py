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
    """tui-ux16r2: active hint docks at the bottom of #messages_box,
    full width, below the log viewport."""
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
        assert hint_region.width == box_region.width
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
