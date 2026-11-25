"""工单 13 — GUI Esc 三级语义 + Ctrl+N 新建对话（对标 TUI 双 Esc / 键位迁移）。

Esc：① 补全弹层开着→关弹层；② 回合进行中且未取消→Esc#1 prime、Esc#2 取消并立即 prime 撤回
（gui-ux15，对标 TUI tui-ux15 三段级联）；③ 空闲或取消收尾（drain）→1.5s 内二 Esc 撤回一轮
（取消已 prime 时单 Esc 即撤回）。单 Esc 永不退 app。
Ctrl+N 走 QShortcut → _on_new_session_clicked。
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
    # gui-ux22 03：Esc 级联逐槽化后实体走 _cancel_slot/_on_undo_for；
    # 零参 _cancel_active/_on_undo 保留作兼容面，一并 patch（主槽逐字等价）
    monkeypatch.setattr(win, "_cancel_active", lambda: record.append("cancel"))
    monkeypatch.setattr(win, "_cancel_slot", lambda slot: record.append("cancel"))
    monkeypatch.setattr(win, "_on_undo", lambda: record.append("undo"))
    monkeypatch.setattr(win, "_on_undo_for", lambda tid: record.append("undo"))
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


def test_running_triple_esc_cascels_to_undo_drain(qapp, monkeypatch):
    """gui-ux15 三击级联（drain 态）：Esc#1 prime 取消 → Esc#2 取消（自动 prime 撤回）→
    Esc#3（gate 收尾中 peek_cancelled=True）直接撤回，不再落入「取消」段。"""
    record: list = []
    win, p = _win(monkeypatch, record)
    flag = {"cancelled": False}
    p.gate.is_running = lambda tid: True
    p.gate.peek_cancelled = lambda tid: flag["cancelled"]
    monkeypatch.setattr(
        win,
        "_cancel_active",
        lambda: (flag.update(cancelled=True), record.append("cancel")),
    )
    monkeypatch.setattr(
        win,
        "_cancel_slot",
        lambda slot: (flag.update(cancelled=True), record.append("cancel")),
    )
    assert win._on_esc_pressed() is True
    assert record == []
    assert "再按一次 Esc 取消执行" in win.status_label.text()
    assert win._on_esc_pressed() is True
    assert record == ["cancel"]
    assert "已取消" in win.status_label.text()
    assert win._on_esc_pressed() is True
    assert record == ["cancel", "undo"]
    assert "已撤回最近一轮" in win.status_label.text()


def test_running_triple_esc_cascels_to_undo_idle(qapp, monkeypatch):
    """gui-ux15 三击级联（取消后 drain 已结束→空闲）：第三击 Esc 直接撤回。"""
    record: list = []
    win, p = _win(monkeypatch, record)
    p.gate.is_running = lambda tid: "cancel" not in record  # 取消前 running，收尾后空闲
    assert win._on_esc_pressed() is True
    assert win._on_esc_pressed() is True
    assert record == ["cancel"]
    assert "已取消" in win.status_label.text()
    assert win._on_esc_pressed() is True
    assert record == ["cancel", "undo"]
    assert "已撤回最近一轮" in win.status_label.text()


def test_cancel_undo_prime_window_still_respected(qapp, monkeypatch):
    """gui-ux15 回归保护：取消后 prime 撤回的 1.5s 窗口仍生效——超窗后须再二 Esc。"""
    record: list = []
    win, p = _win(monkeypatch, record)
    p.gate.is_running = lambda tid: "cancel" not in record
    win._on_esc_pressed()
    win._on_esc_pressed()
    assert record == ["cancel"]
    win._esc_undo_primed_at = 0.0  # 模拟 prime 窗口过期
    assert win._on_esc_pressed() is True
    assert record == ["cancel"]  # 超窗：只重新 prime，不撤回
    assert "再按一次 Esc 撤回最近一轮" in win.status_label.text()
    assert win._on_esc_pressed() is True
    assert record == ["cancel", "undo"]


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
