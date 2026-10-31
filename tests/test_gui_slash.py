"""工单 07 — GUI 输入框 slash 路由：/xxx 走本地命令分发，虚拟路径引用仍发模型。

对标 TUI _handle_user_message 的三分法：普通文本 / slash 命令 / 虚拟路径引用。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import commands
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.test_gui_presenter import _fake_runtime


def _win(qapp, monkeypatch, record: list) -> MainWindow:
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.active_tid = "t-1"
    monkeypatch.setattr(
        win, "_execute_slash", lambda raw: record.append(("slash", raw))
    )
    monkeypatch.setattr(
        win.presenter,
        "start_turn",
        lambda tid, text, **kw: record.append(("turn", tid, text)) or "started",
    )
    return win


def test_plain_text_goes_to_model(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("你好，读一下 README")
    assert ("turn", "t-1", "你好，读一下 README") in record
    assert not [r for r in record if r[0] == "slash"]


def test_slash_command_routes_to_dispatch(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/sessions")
    assert ("slash", "/sessions") in record
    assert not [r for r in record if r[0] == "turn"]


def test_slash_with_args_routes_to_dispatch(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/replay abc123")
    assert ("slash", "/replay abc123") in record


def test_use_command_expands_and_streams(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(
        commands, "expand_use_command", lambda cfg, text: ("[skill:pdf] 读一下", None)
    )
    pane = win._ensure_pane("t-1")
    bubbles: list = []
    monkeypatch.setattr(
        pane, "append_user", lambda text, images: bubbles.append(text)
    )
    win._on_input_submit("/use pdf 读一下")
    assert ("turn", "t-1", "[skill:pdf] 读一下") in record
    assert "/use pdf 读一下" in bubbles
    assert not [r for r in record if r[0] == "slash"]


def test_use_unknown_skill_shows_error(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    monkeypatch.setattr(
        commands, "expand_use_command", lambda cfg, text: (None, "未找到 skill「nope」")
    )
    win._on_input_submit("/use nope")
    assert "未找到 skill「nope」" in win.status_label.text()
    assert not record


def test_virtual_path_reference_stays_model(qapp, monkeypatch):
    record: list = []
    win = _win(qapp, monkeypatch, record)
    win._on_input_submit("/workspace/a.txt")
    assert ("turn", "t-1", "/workspace/a.txt") in record
    assert not [r for r in record if r[0] == "slash"]
