"""PasteTextArea 粘贴链路测试（tui-ux13 起：#input 为 JarvisTextArea，全量多行粘贴）。"""
import asyncio

import pytest

from src import tui
from src.tui import JarvisTextArea


class _FakeAgent:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return "ok"

    async def ainvoke(self, *args, **kwargs):
        return type("R", (), {"content": ""})()

    def invoke(self, *args, **kwargs):
        return type("R", (), {"content": ""})()


def _make_host():
    return tui.JarvisApp(None, _FakeAgent(), {"default": "ask", "tools": {}})


async def _wait_for_text(inp: JarvisTextArea, expected: str, tries: int = 80) -> bool:
    for _ in range(tries):
        if inp.text == expected:
            return True
        await asyncio.sleep(0.05)
    return inp.text == expected


@pytest.mark.asyncio
async def test_ctrl_v_pastes_os_clipboard(monkeypatch):
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "pasted 文本")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "pasted 文本")


@pytest.mark.asyncio
async def test_ctrl_shift_v_pastes_os_clipboard(monkeypatch):
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "shift-paste")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+shift+v")
        assert await _wait_for_text(inp, "shift-paste")


@pytest.mark.asyncio
async def test_mouse_paste_right_and_middle():
    from unittest.mock import patch

    from rich.style import Style

    from textual import events

    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        for button in (2, 3):
            event = events.MouseDown(
                widget=inp,
                x=1,
                y=0,
                delta_x=0,
                delta_y=0,
                button=button,
                shift=False,
                meta=False,
                ctrl=False,
                screen_x=1,
                screen_y=0,
                style=Style(),
            )
            with patch.object(inp, "action_paste") as mock_paste:
                await inp._on_mouse_down(event)
                mock_paste.assert_called_once()

        left_event = events.MouseDown(
            widget=inp,
            x=1,
            y=0,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=1,
            screen_y=0,
            style=Style(),
        )
        with patch.object(inp, "action_paste") as mock_paste:
            await inp._on_mouse_down(left_event)
            mock_paste.assert_not_called()


@pytest.mark.asyncio
async def test_paste_multiline_full_text(monkeypatch):
    """tui-ux13 语义 ①：全量多行粘贴（旧首行裁剪废弃）。"""
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "first\nsecond\nthird")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "first\nsecond\nthird")


def test_read_os_clipboard_smoke():
    """真实环境冒烟：不抛异常即可（内容取决于测试机剪贴板）。"""
    result = tui.read_os_clipboard()
    assert isinstance(result, str)
