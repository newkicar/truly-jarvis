"""工单 13 — GUI Esc 三级语义 + Ctrl+N 新建对话（对标 TUI 双 Esc / 键位迁移）。

Esc：① 补全弹层开着→关弹层；② 回合进行中→1.5s 内二 Esc 取消；③ 空闲→1.5s 内二 Esc 撤回一轮。
单 Esc 永不退 app。Ctrl+N 走 QShortcut → _on_new_session_clicked。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QShortcut
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.test_gui_presenter import _fake_runtime


def _win(monkeypatch, record: list) -> tuple[MainWindow, GuiPresenter]:
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    win.active_tid = "t-1"
    monkeypatch.setattr(win, "_cancel_active", lambda: record.append("cancel"))
    monkeypatch.setattr(win, "_on_undo", lambda: record.append("undo"))
    monkeypatch.setattr(win, "close", lambda: record.append("close"))
    return win, p


def test_idle_single_esc_neither_undoes_nor_quits(qapp, monkeypatch):
    record: list = []
    win, p = _win(monkeypatch, record)
    assert win._on_esc_pressed() is True
    assert "再按一次 Esc 撤回最近一轮" in win.status_label.text()
    assert record == []  # 单 Esc：不撤回、不取消、不退 app


def test_idle_double_esc_undoes_last_turn(qapp, monkeypatch):
    record: list = []
    win, p = _win(monkeypatch, record)
    win._on_esc_pressed()
    assert win._on_esc_pressed() is True
    assert record == ["undo"]
    assert "已撤回最近一轮" in win.status_label.text()


def test_running_single_esc_primes_cancel(qapp, monkeypatch):
    record: list = []
    win, p = _win(monkeypatch, record)
    p.gate.is_running = lambda tid: True
    assert win._on_esc_pressed() is True
    assert record == []
    assert "再按一次 Esc 取消执行" in win.status_label.text()


def test_running_double_esc_cancels(qapp, monkeypatch):
    record: list = []
    win, p = _win(monkeypatch, record)
    p.gate.is_running = lambda tid: True
    win._on_esc_pressed()
    assert win._on_esc_pressed() is True
    assert record == ["cancel"]
    assert "已取消" in win.status_label.text()


def test_completion_popup_takes_esc_priority(qapp, monkeypatch):
    record: list = []
    win, p = _win(monkeypatch, record)
    monkeypatch.setattr(win, "_completion_esc_dismiss", lambda: True)
    assert win._on_esc_pressed() is True
    assert record == []  # 只关弹层，不触碰取消/撤回
    assert win._esc_run_primed is False
    assert win._esc_undo_primed is False


def test_ctrl_n_shortcut_creates_new_session(qapp, monkeypatch):
    rt = _fake_runtime()
    p = GuiPresenter(rt, UiBridge())
    win = MainWindow(p, p.bridge)
    sc = [x for x in win.findChildren(QShortcut) if x.key().toString() == "Ctrl+N"]
    assert len(sc) == 1
    hits: list = []
    monkeypatch.setattr(win, "_switch_to", lambda tid: hits.append(tid))
    monkeypatch.setattr(p, "new_session_id", lambda: "t-new")
    sc[0].activated.emit()
    assert hits == ["t-new"]
