# -*- coding: utf-8 -*-
"""gui15 #1/#12/extra——常驻工作状态徽标 + 醒目模式徽标 + 主题换肤重着色。

徽标语义（main_window._refresh_running_badge）：
idle/running/awaiting/stopped 四态独立于 status_label，
切主题（_on_theme）时全量重着色。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import commands
from src.gui import theme as theme_mod
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home, new_home
from tests.test_gui_presenter import _fake_runtime


def _win(qapp):
    home = new_home()
    rt = _fake_runtime()
    bridge = UiBridge()
    p = GuiPresenter(rt, bridge)
    return MainWindow(p, bridge), p, rt, home


def test_running_badge_idle_to_running_to_idle(qapp):
    """#1：工作状态徽标 idle→running→idle，文本随 gate 状态流转。"""
    win, p, rt, home = _win(qapp)
    try:
        win._switch_to("s1")
        assert win._running_badge_state == "idle"
        assert win.running_badge.text() == ""

        assert p.gate.try_start("s1", "hello") == "started"
        win._on_turn_started("s1")
        assert win._running_badge_state == "running"
        assert "工作中" in win.running_badge.text()

        p.gate.finish("s1")
        win._on_turn_done("s1", True)
        assert win._running_badge_state == "idle"
        assert win.running_badge.text() == ""
    finally:
        cleanup_home(home)


def test_running_badge_awaiting_card_then_focus_input(qapp):
    """#1：审批卡挂出 = awaiting 态；focus_input（决策完成/输入）回落 running。"""
    win, p, rt, home = _win(qapp)
    try:
        win._switch_to("s1")
        p.gate.try_start("s1", "hello")
        win._on_turn_started("s1")

        inv = commands.ToolInvocation(name="execute", path="echo hi", args={"command": "echo hi"})
        payload = [inv, ["echo hi"], "card-1", lambda r: None, lambda: None]
        win._on_create_card("s1", payload, "card-1")
        assert win.panes["s1"].awaiting_card is True
        assert win._running_badge_state == "awaiting"
        assert "等待审批" in win.running_badge.text()

        win._on_focus_input("s1")
        assert win.panes["s1"].awaiting_card is False
        assert win._running_badge_state == "running"

        p.gate.finish("s1")
        win._on_turn_done("s1", True)
        assert win._running_badge_state == "idle"
    finally:
        cleanup_home(home)


def test_running_badge_stopped_then_cleared_on_restart(qapp):
    """#1：取消/失败后 status「已停止」= stopped 态；再开回合自动清零。"""
    win, p, rt, home = _win(qapp)
    try:
        win._switch_to("s1")
        p.gate.try_start("s1", "hello")
        win._on_turn_started("s1")

        p.gate.finish("s1")
        win._on_turn_done("s1", False)
        win._on_status("s1", "已停止")
        assert win.panes["s1"].stopped is True
        assert win._running_badge_state == "stopped"
        assert "已停止" in win.running_badge.text()

        # 再开回合：stopped 清零，回到 running
        p.gate.try_start("s1", "again")
        win._on_turn_started("s1")
        assert win.panes["s1"].stopped is False
        assert win._running_badge_state == "running"
    finally:
        cleanup_home(home)


def test_mode_badge_pill_yolo(qapp):
    """#12：模式徽标 rich HTML 加粗（[Act]/[Plan] + [YOLO]），YOLO 随会话显隐。"""
    win, p, rt, home = _win(qapp)
    try:
        win._switch_to("s1")
        assert "[Act]" in win.mode_badge.text()
        assert "font-weight: bold" in win.mode_badge.text()

        win.yolo_action.setChecked(True)
        assert "[YOLO]" in win.mode_badge.text()
        win.yolo_action.setChecked(False)
        assert "YOLO" not in win.mode_badge.text()
    finally:
        cleanup_home(home)


def test_show_text_scrollable_dialog(qapp, monkeypatch):
    """#14/G7：长文（/help 等）走可滚动 + 可拖选对话框，不再压状态栏。"""
    from PySide6.QtWidgets import QDialog, QLabel, QScrollArea

    holder = {}
    monkeypatch.setattr(QDialog, "exec", lambda self: (holder.update(d=self), 0)[1])

    win, p, rt, home = _win(qapp)
    try:
        win._show_text("命令帮助", "a\nb")
        d = holder.get("d")
        assert d is not None and isinstance(d, QDialog)
        assert d.findChild(QScrollArea) is not None
        lbl = d.findChild(QLabel, "report-label")
        assert lbl is not None
        assert "b" in lbl.text()
    finally:
        cleanup_home(home)


def test_theme_switch_recolors_badges(qapp, monkeypatch):
    """#13/extra：切主题后徽标跟随新 token 重着色（零重建）。"""
    monkeypatch.setattr(theme_mod, "save_theme", lambda name: None)
    monkeypatch.setattr(theme_mod, "apply_theme", lambda app, name: None)

    win, p, rt, home = _win(qapp)
    try:
        win._switch_to("s1")
        p.gate.try_start("s1", "hello")
        win._on_turn_started("s1")
        assert "工作中" in win.running_badge.text()

        win._on_theme("nord")
        assert "工作中" in win.running_badge.text()
        assert win.running_badge.styleSheet() != ""
    finally:
        cleanup_home(home)