# #01 回归：对话区鼠标拖选 + 松开自动复制（Textual 8.2.8 API）。
# 用户症状：拖选看不到选区、没有「已复制」提示、系统剪贴板内容不变。
from __future__ import annotations

import pytest

from textual import events
from textual.app import App, ComposeResult

import src.tui_log as tui_log_mod
from src.tui_log import CopyableRichLog


class DragSelectApp(App):
    """最小复现：一个 CopyableRichLog，copy_on_select=True。

    与 JarvisApp 相同的装配方式（widget 级 ALLOW_SELECT + app 级 ALLOW_SELECT）。
    """

    ALLOW_SELECT = True

    def __init__(self) -> None:
        super().__init__()
        self.copied: list[str] = []

    def compose(self) -> ComposeResult:
        yield CopyableRichLog(id="log", copy_on_select=True, max_lines=200)

    def on_text_selected(self, event: events.TextSelected) -> None:
        """镜像 JarvisApp.on_text_selected（#01 修复的 app 级挂载）。"""
        log = self.query_one("#log", CopyableRichLog)
        if not log.copy_on_select:
            return
        ok, text = log.copy_selection_to_clipboard()
        if text and ok:
            self.copied.append(text)


async def _wait(pilot, cond, rounds: int = 30) -> None:
    """8.2.8 Pilot 没有 wait_for：用 pause 轮询代替。"""
    for _ in range(rounds):
        if cond():
            return
        await pilot.pause()
    raise AssertionError("等待条件超时")


async def _drag_select(pilot, start: tuple[int, int], end: tuple[int, int]) -> None:
    """mouse_down(start) → MouseMove(end, 按住) → mouse_up(end)。

    8.2.8 的 Pilot 没有 mouse_move；用私有 _post_mouse_events 补一次按住移动。
    """
    await pilot.mouse_down("#log", start, button=1)
    await pilot._post_mouse_events(  # noqa: SLF001
        [events.MouseMove], widget="#log", offset=end, button=1
    )
    await pilot.mouse_up("#log", end)
    await pilot.pause()


@pytest.mark.asyncio
async def test_drag_select_creates_screen_selection(monkeypatch):
    """拖选后 Screen.selections 必须非空（选区高亮的前提）。"""
    monkeypatch.setattr(tui_log_mod, "copy_text_to_system_clipboard", lambda t: True)
    app = DragSelectApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", CopyableRichLog)
        log.write("hello world")
        log.write("second line")
        log.write("third line")
        await _wait(pilot, lambda: log.plain_text().count("\n") >= 2)

        await _drag_select(pilot, (2, 1), (6, 3))

        assert pilot.app.screen.selections, "拖选后选区为空（选区高亮不会出现）"


@pytest.mark.asyncio
async def test_drag_select_releases_copies_to_system_clipboard(monkeypatch):
    """拖选松开后系统剪贴板写入被触发（copy_on_select=True 的既有契约）。"""
    calls: list[str] = []

    def fake_copy(text: str) -> bool:
        calls.append(text)
        return True

    monkeypatch.setattr(tui_log_mod, "copy_text_to_system_clipboard", fake_copy)
    app = DragSelectApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", CopyableRichLog)
        log.write("alpha one")
        log.write("alpha two")
        log.write("alpha three")
        await _wait(pilot, lambda: log.plain_text().count("\n") >= 2)

        assert not calls, "未拖选前不应有复制"
        await _drag_select(pilot, (2, 1), (8, 2))

        assert calls, "拖选松开后未触发系统剪贴板复制（用户症状：剪贴板内容不变）"
        joined = calls[-1]
        assert "alpha" in joined, f"复制内容不对: {joined!r}"


@pytest.mark.asyncio
async def test_drag_select_off_switch_disables_copy(monkeypatch):
    """copy_on_select=False 时拖选不触发复制（保持既有开关语义）。"""
    calls: list[str] = []
    monkeypatch.setattr(
        tui_log_mod, "copy_text_to_system_clipboard", lambda t: calls.append(t) or True
    )

    class NoCopyApp(DragSelectApp):
        def compose(self) -> ComposeResult:
            yield CopyableRichLog(id="log", copy_on_select=False, max_lines=200)

    app = NoCopyApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", CopyableRichLog)
        log.write("beta one")
        log.write("beta two")
        await _wait(pilot, lambda: log.plain_text().count("\n") >= 1)
        await _drag_select(pilot, (2, 1), (8, 2))
        assert not calls, "copy_on_select=False 时不应复制"


@pytest.mark.asyncio
async def test_plain_text_828_strip_shape(monkeypatch):
    """8.2.8 下 Strip 迭代出 Segment(text, style, control)，plain_text 不炸且内容正确。"""
    monkeypatch.setattr(tui_log_mod, "copy_text_to_system_clipboard", lambda t: True)
    app = DragSelectApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", CopyableRichLog)
        log.write("line A")
        log.write("line B")
        await _wait(pilot, lambda: log.plain_text().count("\n") >= 1)
        text = log.plain_text()
        assert "line A" in text and "line B" in text
        assert log.selected_plain_text() == ""
