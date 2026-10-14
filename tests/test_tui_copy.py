"""#01 TUI 复制（copy picker + 剪贴板级联 + 默认值）测试。"""
import sys
from typing import Any

import pytest

from src import commands
from src.tui_log import (
    copy_text_to_system_clipboard,
    copy_via_powershell,
    copy_via_win32,
)
from src.tui import CopyPickerModal, JarvisApp

F = '```'
FENCE = F


def _msg(role: str, text: str) -> Any:
    return type("M", (), {"type": role, "content": text})()


class _FakeState:
    def __init__(self, values):
        self.values = values


class _HistoryAgent:
    """get_state_history 返回单元素 list（history[0]=最新重建状态）。"""

    def __init__(self, messages):
        self._messages = messages

    def get_state_history(self, config=None):
        return iter([_FakeState({"messages": self._messages})] * 1)

    def get_state(self, config=None):
        return _FakeState({"messages": self._messages})


# ---- commands.last_code_block ----

def test_last_code_block_returns_last_fenced_block():
    text = f"前言\n{F}py\nx = 1\n{F}\n正文\n{F}\nfinal\n{F}"
    assert commands.last_code_block(text) == f"{F}\nfinal\n{F}"


def test_last_code_block_with_language_tag_and_nested_lookalike():
    text = f"a\n{F}js\ncode\n{F}\nb"
    assert commands.last_code_block(text) == f"{F}js\ncode\n{F}"


def test_last_code_block_no_fences_returns_empty():
    assert commands.last_code_block("没有围栏") == ""
    assert commands.last_code_block("") == ""


# ---- commands.render_session_text ----

def test_render_session_text_roles_and_order():
    agent = _HistoryAgent(
        [
            _msg("human", "第一句"),
            _msg("ai", "AI 回 1"),
            _msg("tool", "tool result 应被跳过"),
            _msg("human", "第二句"),
            _msg("ai", "AI 回 2"),
        ]
    )
    text = commands.render_session_text(agent, "t1")
    assert text == "[user] 第一句\n\n[JARVIS] AI 回 1\n\n[user] 第二句\n\n[JARVIS] AI 回 2"


def test_render_session_text_empty_history():
    agent = _HistoryAgent([])
    assert commands.render_session_text(agent, "t1") == ""


# ---- dispatch: /copy TUI-only hint ----

def test_dispatch_copy_returns_tui_hint():
    text, new_thread, replay = commands.dispatch_command(None, "t1", "/copy")
    assert "TUI" in text and "/copy-session" in text
    assert new_thread is None and replay is None


# ---- tui_log 级联 ----

def test_copy_cascade_win32_success_short_circuits(monkeypatch):
    calls: list[str] = []
    import src.tui_log as tl

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(tl, "copy_via_win32", lambda text, attempts=2: calls.append("win32") or True)
    monkeypatch.setattr(tl, "copy_via_powershell", lambda text: (calls.append("ps"), False)[1])
    assert copy_text_to_system_clipboard("hi") is True
    assert calls == ["win32"]


def test_copy_cascade_falls_back_to_powershell(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sys, "platform", "win32")
    import src.tui_log as tl

    monkeypatch.setattr(tl, "copy_via_win32", lambda text, attempts=2: calls.append("win32") or False)
    monkeypatch.setattr(tl, "copy_via_powershell", lambda text: (calls.append("ps"), True)[1])
    assert copy_text_to_system_clipboard("hi") is True
    assert calls == ["win32", "ps"]


def test_copy_cascade_empty_or_non_windows_returns_false(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert copy_text_to_system_clipboard("hi") is False
    assert copy_text_to_system_clipboard("") is False


def test_copy_via_win32_requires_text_and_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert copy_via_win32("hi") is False
    assert copy_via_powershell("hi") is False


# ---- JarvisApp ----

def test_copy_on_select_defaults_true():
    import types

    app = JarvisApp(None, None, {"default": "ask", "tools": {}})
    # config 缺失 → False（最小 app）；config 在但 tui 无键 → fallback True（#01 C3）
    assert app._copy_on_select() is False
    app.config = types.SimpleNamespace(tui={})
    assert app._copy_on_select() is True
    app.config = types.SimpleNamespace(tui={"copy_on_select": False})
    assert app._copy_on_select() is False


def test_copy_picker_modal_picks_latest_ai_reply():
    agent = _HistoryAgent(
        [
            _msg("human", "q"),
            _msg("ai", f"回答\n{F}py\nprint(1)\n{F}"),
        ]
    )
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}}, thread_id="t1")
    modal = CopyPickerModal(app)
    assert modal._pick_text("ai").endswith(FENCE)
    assert modal._pick_text("code") == f"{F}py\nprint(1)\n{F}"
    assert modal._pick_text("session") == f"[user] q\n\n[JARVIS] 回答\n{F}py\nprint(1)\n{F}"
    assert modal._pick_text("bogus") == ""


def test_copy_picker_modal_without_agent():
    app = JarvisApp(None, None, {"default": "ask", "tools": {}})
    modal = CopyPickerModal(app)
    assert modal._pick_text("ai") == ""
