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


def test_yolo_slash_off_resyncs_ui_surfaces(qapp, monkeypatch):
    """命令 /yolo off 改共享 permission_state 后，菜单勾选 / [YOLO] 徽标 / 状态栏须联动。"""
    from src import permissions

    win, p, rt, home = _win(qapp)
    try:
        state = rt.permission_state
        win._switch_to("sess-a")
        win.yolo_action.setChecked(True)  # 菜单开 YOLO
        assert win.yolo_action.isChecked()
        assert "[YOLO]" in win.mode_badge.text()
        calls = []
        # 同步化 run_command（内联执行 worker fn，queued 信号同线程直连即时生效）
        monkeypatch.setattr(
            p, "run_command", lambda fn, tid: calls.append(tid) or fn()
        )
        win._execute_slash("/yolo off")
        assert calls == ["sess-a"]
        assert not permissions.yolo_active(state, "sess-a")
        assert not win.yolo_action.isChecked()
        assert "[YOLO]" not in win.mode_badge.text()
        assert "YOLO 已关闭" in win.status_label.text()
    finally:
        cleanup_home(home)


def test_yolo_slash_on_resyncs_ui_surfaces(qapp, monkeypatch):
    """反向：/yolo on 经命令开启后，菜单勾选与 [YOLO] 徽标同步点亮。"""
    from src import permissions

    win, p, rt, home = _win(qapp)
    try:
        state = rt.permission_state
        win._switch_to("sess-a")
        assert not win.yolo_action.isChecked()
        monkeypatch.setattr(
            p, "run_command", lambda fn, tid: fn()
        )
        win._execute_slash("/yolo on")
        assert permissions.yolo_active(state, "sess-a")
        assert win.yolo_action.isChecked()
        assert "[YOLO]" in win.mode_badge.text()
        assert "YOLO 已开启" in win.status_label.text()
    finally:
        cleanup_home(home)


def test_undo_noop_without_active_session(qapp):
    win, p, rt, home = _win(qapp)
    try:
        win.active_tid = None
        win._on_undo()  # 无会话 → 不崩
    finally:
        cleanup_home(home)


def _fake_qinput_get_int(result):
    """模拟真实 PySide6 SIP 绑定：位置参数 (parent, title, label, value, min, max, step) 全支持；
    min=/max= keyword 抛 AttributeError（本版本实证，value=/step= keyword 可用）。
    被测代码若退回 min=/max= keyword 形式，测试会复现与生产一致的错误而非静默吞掉。"""
    calls = []

    def fake(parent, title, label, value=0, _min=0, _max=99, step=1, **kw):
        for name in ("min", "max"):
            if name in kw:
                raise AttributeError(
                    f"PySide6.QtWidgets.QInputDialog.getInt(): unsupported keyword '{name}'"
                )
        calls.append((value, _min, _max, step))
        return result

    fake.calls = calls
    return fake


def test_advanced_menu_contains_auto_compaction_action(qapp):
    """高级菜单含「自动压缩上下文阈值…」入口（gui15 G3 auto_compaction 写回）"""
    win, p, rt, home = _win(qapp)
    try:
        texts = [a.text() for a in win._advanced_menu.actions()]
        assert "自动压缩上下文阈值…" in texts
    finally:
        cleanup_home(home)


def test_set_auto_compaction_saves_and_reports(qapp, monkeypatch):
    """对话框确认后调 save_auto_compaction(v) 写**全局** jarvis.json，状态栏显示「已写入/全局配置」（gui15 G3 auto_compaction 写回，全局语义）"""
    win, p, rt, home = _win(qapp)
    try:
        import src.config
        from PySide6.QtWidgets import QInputDialog

        saves = []
        fake = _fake_qinput_get_int((12000, True))
        monkeypatch.setattr(QInputDialog, 'getInt', fake)
        monkeypatch.setattr(
            src.config, 'save_auto_compaction',
            lambda v: saves.append(v) or (home / 'jarvis.json'),
        )
        win._on_set_auto_compaction()
        assert len(saves) == 1
        assert saves[0] == 12000
        assert "已写入" in win.status_label.text()
        assert "全局配置" in win.status_label.text()  # 写的是全局 ~/.jarvis/jarvis.json
        assert str(home / "jarvis.json") in win.status_label.text()
        # 对话框必须位置传参（current 缺省 0 / min=0 / max=200000 / step=1000）——
        # 代码若退回 min=/max= keyword，fake 抛 AttributeError 使本测试红灯
        assert fake.calls == [(0, 0, 200000, 1000)]
    finally:
        cleanup_home(home)


def test_set_auto_compaction_cancel_no_save(qapp, monkeypatch):
    """对话框取消不落盘（gui15 G3 auto_compaction 写回）"""
    win, p, rt, home = _win(qapp)
    try:
        import src.config
        from PySide6.QtWidgets import QInputDialog

        saves = []
        fake = _fake_qinput_get_int((0, False))
        monkeypatch.setattr(QInputDialog, 'getInt', fake)
        monkeypatch.setattr(
            src.config, 'save_auto_compaction',
            lambda v: saves.append(v) or (home / 'jarvis.json'),
        )
        win._on_set_auto_compaction()
        assert not saves
        assert fake.calls == [(0, 0, 200000, 1000)]
    finally:
        cleanup_home(home)


def test_auto_compaction_menu_enabled_when_active(qapp):
    """活跃项目态：高级菜单「自动压缩上下文阈值…」可用（gui15 空态 UX：防止误以为按钮失效）"""
    win, p, rt, home = _win(qapp)
    try:
        assert win._compact_action.isEnabled()
    finally:
        cleanup_home(home)


def test_set_auto_compaction_empty_state_hints_status(qapp):
    """空态（presenter=None，生产路径 = 空注册表 WorkspaceController）：菜单项置灰；
    手动触发处理器不崩且状态栏给引导（不再静默 return）"""
    from src.gui.project_registry import ProjectRegistry
    from src.gui.workspace_controller import WorkspaceController

    home = new_home()
    try:
        controller = WorkspaceController(
            ProjectRegistry(home / "projects.json"),
            lambda root: None,  # 空注册表：factory 不会被调
            UiBridge(),
        )
        win = MainWindow(None, controller.bridge, workspace=controller)
        assert not win._compact_action.isEnabled()
        win._on_set_auto_compaction()
        assert "活动项目" in win.status_label.text()
    finally:
        cleanup_home(home)
