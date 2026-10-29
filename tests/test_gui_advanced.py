"""工单 08 — 高级模式与撤回（Plan/Act 全局 · YOLO 线程级 · /undo 消息层）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import plan_mode
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import new_home, cleanup_home
from tests.test_gui_presenter import _fake_runtime, wait_until


def _win(qapp):
    home = new_home()
    rt = _fake_runtime()
    bridge = UiBridge()
    p = GuiPresenter(rt, bridge)
    win = MainWindow(p, bridge)
    return win, p, rt, home


def test_plan_mode_toggle_sets_state_and_badge(qapp):
    from src import permissions  # noqa: F401 (yolo 共用同一 state)

    win, p, rt, home = _win(qapp)
    try:
        state = rt.permission_state
        win._switch_to("sess-plan")
        assert plan_mode.current_mode(state) == "act"
        win.plan_action.setChecked(True)  # 触发 _on_plan_toggled
        assert plan_mode.current_mode(state) == "plan"
        assert win.plan_action.isChecked()
        assert "[Plan]" in win.mode_badge.text()
        win.plan_action.setChecked(False)
        assert plan_mode.current_mode(state) == "act"
        assert "[Act]" in win.mode_badge.text()
    finally:
        cleanup_home(home)


def test_yolo_is_thread_scoped(qapp):
    from src import permissions

    win, p, rt, home = _win(qapp)
    try:
        state = rt.permission_state
        win._switch_to("sess-a")
        win.yolo_action.setChecked(True)
        assert permissions.yolo_active(state, "sess-a")
        assert "[YOLO]" in win.mode_badge.text()
        # 切到另一会话：YOLO 不串（per-thread）
        win._switch_to("sess-b")
        assert not permissions.yolo_active(state, "sess-b")
        assert "[YOLO]" not in win.mode_badge.text()
        assert not win.yolo_action.isChecked()  # 勾选态随会话同步
        # 关闭
        win._switch_to("sess-a")
        win.yolo_action.setChecked(False)
        assert not permissions.yolo_active(state, "sess-a")
    finally:
        cleanup_home(home)


def test_undo_dispatches_command_and_rebuilds(qapp, monkeypatch):
    from src import commands
    from src.gui import replay

    win, p, rt, home = _win(qapp)
    try:
        calls = {"undo": [], "rebuild": []}
        monkeypatch.setattr(
            commands, "undo", lambda agent, tid, n=1: calls["undo"].append(tid) or "已撤回 1 条"
        )
        monkeypatch.setattr(
            replay, "thread_record", lambda agent, tid, **k: []
        )
        win._switch_to("sess-u")
        # 真实 worker 线程跑 run_command：等 notify + rebuild_pane 落地
        notified = {"n": 0}
        win.bridge.notify.connect(lambda s: notified.__setitem__("n", notified["n"] + 1))
        win._on_undo()
        assert wait_until(lambda: calls["undo"] == ["sess-u"], timeout=10.0)
        assert wait_until(lambda: notified["n"] >= 1, timeout=10.0)
    finally:
        cleanup_home(home)


def test_undo_noop_without_active_session(qapp):
    win, p, rt, home = _win(qapp)
    try:
        win.active_tid = None
        win._on_undo()  # 无会话 → 不崩
    finally:
        cleanup_home(home)
