"""工单 08 — 高级模式与撤回（Plan/Act 全局 · YOLO 线程级 · /undo 消息层）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import plan_mode
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home, new_home
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


def test_undo_file_hint_reaches_status_bar(qapp, monkeypatch):
    """2026-11-20（方向 A）：undo 返回串尾部追加的回退指引行（撤区段含文件写工具）
    经 worker notify → 状态栏整串透出（GUI 零 UI 改动；\n 保留）。"""
    from src import commands
    from src.gui import replay

    win, p, rt, home = _win(qapp)
    try:
        hint = (
            "已撤回 1 条消息（仅消息层；文件未动；HITL 悬挂已作废）\n"
            "提示：撤回区段含文件修改工具（write_file），文件未随之回退；"
            "需回退文件请先 /snapshot 再 /rollback <快照短id>（/snapshots 查清单）。"
        )
        monkeypatch.setattr(commands, "undo", lambda agent, tid, n=1: hint)
        monkeypatch.setattr(commands, "last_user_input", lambda agent, tid: "")
        monkeypatch.setattr(replay, "thread_record", lambda agent, tid, **k: [])
        win._switch_to("sess-u2")
        win._on_undo()
        assert wait_until(
            lambda: "提示：撤回区段含文件修改工具" in win.status_label.text(),
            timeout=10.0,
        )
        assert "write_file" in win.status_label.text()
        assert "/snapshot" in win.status_label.text()
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
        from PySide6.QtWidgets import QInputDialog

        import src.config

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
        from PySide6.QtWidgets import QInputDialog

        import src.config

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

def test_undo_backfills_input_box_on_success(qapp, monkeypatch):
    """gui-ux16：undo 成功 → 被撤回的用户消息经 input_set 回填输入框（对标 codex：可改可再发）。

    gui-ux22 03：input_set 载荷双参 (tid, text)——按「被撤回会话」路由，不再随 active_tid 漂移。
    """
    from src import commands
    from src.gui import replay

    win, p, rt, home = _win(qapp)
    try:
        monkeypatch.setattr(commands, "undo", lambda agent, tid, n=1: "已撤回 1 条")
        monkeypatch.setattr(commands, "last_user_input", lambda agent, tid: "这个人叫什么")
        monkeypatch.setattr(replay, "thread_record", lambda agent, tid, **k: [])
        monkeypatch.setattr(p, "run_command", lambda fn, tid: fn())
        win._switch_to("sess-bf")
        captured = []
        win.bridge.input_set.connect(lambda tid, text: captured.append((tid, text)))
        win._on_undo()
        assert captured == [("sess-bf", "这个人叫什么")]
        assert win.input_bar.edit.toPlainText() == "这个人叫什么"  # 双参 handler 回填主槽输入条
    finally:
        cleanup_home(home)


def test_undo_no_input_backfill_on_failure_or_empty(qapp, monkeypatch):
    """gui-ux16：撤回失败 / 空白无目标 / 无用户消息可取 → 一律不回填输入框。"""
    from src import commands
    from src.gui import replay

    cases = [
        ("撤回失败：消息缺少 id，无法定位（请 /delete-session 新开会话）", "这个人叫什么", "失败不回填"),
        ("没有可撤回的消息", "这个人叫什么", "空白无目标不回填"),
        ("已撤回 1 条", "", "无用户消息可取不回填"),
    ]
    for undo_ret, last_in, note in cases:
        win, p, rt, home = _win(qapp)
        try:
            monkeypatch.setattr(commands, "undo", lambda agent, tid, n=1: undo_ret)
            monkeypatch.setattr(commands, "last_user_input", lambda agent, tid: last_in)
            monkeypatch.setattr(replay, "thread_record", lambda agent, tid, **k: [])
            monkeypatch.setattr(p, "run_command", lambda fn, tid: fn())
            win._switch_to("sess-bf2")
            captured = []
            win.bridge.input_set.connect(lambda tid, text: captured.append((tid, text)))
            win._on_undo()
            assert captured == [], note
        finally:
            cleanup_home(home)


def test_slash_undo_routes_by_slot_tid(qapp, monkeypatch):
    """gui-ux22 03：输入框 /undo 按槽 tid 直接进 _on_undo_for（侧槽 /undo 作用于 side tid，不走零参 _on_undo）。"""
    from src.gui import replay

    win, p, rt, home = _win(qapp)
    try:
        monkeypatch.setattr(replay, "thread_record", lambda agent, tid, **k: [])
        monkeypatch.setattr(p, "run_command", lambda fn, tid: fn())
        win._switch_to("sess-s")
        hits = []
        monkeypatch.setattr(win, "_on_undo_for", lambda tid: hits.append(tid))
        assert win._route_slash("/undo") is True
        assert hits == ["sess-s"]
        # 带参 → 不执行，提示用法
        assert win._route_slash("/undo 2") is True
        assert hits == ["sess-s"]
        assert "用法: /undo（无参）" in win.status_label.text()
    finally:
        cleanup_home(home)


def test_undo_backfill_routes_by_unundown_tid_in_split(qapp, monkeypatch):
    """gui-ux22 03 bug③：active_tid 已漂移到侧会话时，主线 undo 的回填仍进主槽输入条，不写侧框；
    侧线 undo 的回填进侧输入条，主框不动（双槽「按被操作会话路由」回归）。"""
    from src import commands, permissions
    from src.gui import replay

    win, p, rt, home = _win(qapp)
    try:
        permissions.side_open(rt.permission_state, "side-1", "main-1")
        monkeypatch.setattr(commands, "undo", lambda agent, tid, n=1: "已撤回 1 条")
        monkeypatch.setattr(commands, "last_user_input", lambda agent, tid: "主对话最后一条")
        monkeypatch.setattr(replay, "thread_record", lambda agent, tid, **k: [])
        monkeypatch.setattr(p, "run_command", lambda fn, tid: fn())
        win._switch_to("main-1")
        win._switch_to("side-1")  # active_tid 漂移到侧会话（用户症状复现前置）
        assert win._slot_of_tid("main-1") == "main" and win._slot_of_tid("side-1") == "side"
        # 主线 undo → 回填主槽输入条，侧框保持空
        win._on_undo_for("main-1")
        assert win.input_bar.edit.toPlainText() == "主对话最后一条"
        assert win.side_input_bar.edit.toPlainText() == ""
        # 侧线 undo → 回填侧槽输入条，主框不动
        monkeypatch.setattr(commands, "last_user_input", lambda agent, tid: "侧对话最后一条")
        win._on_undo_for("side-1")
        assert win.side_input_bar.edit.toPlainText() == "侧对话最后一条"
        assert win.input_bar.edit.toPlainText() == "主对话最后一条"
    finally:
        cleanup_home(home)
