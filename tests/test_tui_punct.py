"""#02 标点快插面板 + conhost 探测 单测。"""

from __future__ import annotations

import os
import sys

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, OptionList

from src.tui import PunctPanelModal
from src.tui_punct import PUNCT_ITEMS, ime_hint_line, is_conhost_like


class _HostApp(App):
    """测试宿主：模拟 JarvisApp 的 Ctrl+. 绑定 + #input 输入框。"""

    BINDINGS = [Binding("ctrl+.", "punct_panel", "标点面板")]

    def __init__(self) -> None:
        super().__init__()
        self.panel_opened = 0

    def compose(self) -> ComposeResult:
        yield Input(id="input")

    def action_punct_panel(self) -> None:
        self.panel_opened += 1
        self.push_screen(PunctPanelModal(self))

    def _insert_punctuation(self, char: str) -> None:
        box = self.query_one("#input", Input)
        if box.selection:
            box.replace(char, *box.selection)
        else:
            box.insert_text_at_cursor(char)
        box.focus()


def test_punct_items_unique_and_cover_core() -> None:
    chars = [c for c, _ in PUNCT_ITEMS]
    assert len(chars) == len(set(chars))
    assert len(chars) >= 20
    for c in "…“”《》～—·，。、！？：；":
        assert c in chars


def test_ime_hint_line_modes() -> None:
    assert ime_hint_line("off", True) == ""
    assert ime_hint_line("off", False) == ""
    assert "Ctrl" in ime_hint_line("on", False)
    assert ime_hint_line("auto", True) != ""
    assert ime_hint_line("auto", False) == ""
    assert ime_hint_line("bogus", True) != ""  # 非法值回落 auto


def _clean_punct_env(monkeypatch) -> None:
    for key in [k for k in os.environ if k.startswith("WT_") or k.lower().startswith("conemu")]:
        monkeypatch.delenv(key, raising=False)


def test_is_conhost_like_non_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert not is_conhost_like()


def test_is_conhost_like_plain_conhost(monkeypatch) -> None:
    _clean_punct_env(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    assert is_conhost_like()


def test_is_conhost_like_windows_terminal(monkeypatch) -> None:
    _clean_punct_env(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WT_SESSION", "0")
    assert not is_conhost_like()


def test_is_conhost_like_conemu(monkeypatch) -> None:
    _clean_punct_env(monkeypatch)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ConEmuPid", "1234")
    assert not is_conhost_like()


async def _wait_panel_closed(app, pilot) -> None:
    for _ in range(100):
        if not isinstance(app.screen, PunctPanelModal):
            return
        await pilot.pause()
    raise AssertionError("面板未在预期内关闭")


async def test_punct_panel_enter_inserts(monkeypatch) -> None:
    """Ctrl+. 开面板 → 选 “ 回车 → 输入框追加该字符。"""
    _clean_punct_env(monkeypatch)
    app = _HostApp()
    async with app.run_test(size=(80, 30)) as pilot:
        box = app.query_one("#input", Input)
        box.insert_text_at_cursor("ab")
        await pilot.press("ctrl+.")
        assert app.panel_opened == 1
        target = {c: i for i, (c, _) in enumerate(PUNCT_ITEMS)}["“"]
        modal = app.screen
        assert isinstance(modal, PunctPanelModal)
        modal.query_one("#punct_list", OptionList).highlighted = target
        await pilot.press("enter")
        await _wait_panel_closed(app, pilot)
        assert box.value == "ab“"


async def test_punct_panel_replaces_selection() -> None:
    """有选区时标点替换选区。"""
    app = _HostApp()
    async with app.run_test(size=(80, 30)) as pilot:
        box = app.query_one("#input", Input)
        box.insert_text_at_cursor("ab")
        box.select_all()
        assert box.selection
        app._insert_punctuation("，")
        assert box.value == "，"


async def test_punct_panel_esc_closes() -> None:
    """Esc 关闭面板，不插入。"""
    app = _HostApp()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.press("ctrl+.")
        assert app.panel_opened == 1
        await pilot.press("escape")
        await _wait_panel_closed(app, pilot)
        assert app.query_one("#input", Input).value == ""
