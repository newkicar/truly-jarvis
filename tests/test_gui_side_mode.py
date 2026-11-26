"""GUI 侧边会话隔离回归：side 聚焦/开/关不得污染主线 YOLO/Plan 的显示面与状态写。

症状（对标 codex 隔离）：GUI 里开侧边会话后，主对话的 [Plan]/[Act] 徽标翻转、
YOLO 勾选被取消、菜单 YOLO 开关写错线程（side tid 而非主线 tid）。
内核已保证（plan_mode.effective_mode 对 side 强制 plan、全局 mode 键不因 side 变，
见 src/plan_mode.py docstring 与 test_side.py）——本文件钉住 GUI 显示层与写路径。

纪律：不用 tmp_path（本机 WinError 5 中毒）；_fake_runtime 自建 home（agent=None，
仅走纯 state 委托路径，checkpoint fork 由 test_side.py 覆盖）。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import permissions, plan_mode
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter
from tests.gui_fakes import cleanup_home
from tests.test_gui_presenter import _fake_runtime


def _win(qapp):
    rt = _fake_runtime()
    bridge = UiBridge()
    p = GuiPresenter(rt, bridge)
    win = MainWindow(p, bridge)
    return win, p, rt


def _side_setup(win, rt):
    """主线 main-1 开 YOLO + 登记 side-1（parent=main-1）并聚焦 side。"""
    state = rt.permission_state
    permissions.side_open(state, "side-1", "main-1")
    win._switch_to("main-1")
    win.yolo_action.setChecked(True)
    assert permissions.yolo_active(state, "main-1")
    win._switch_to("side-1")


def test_side_focus_keeps_main_state_intact(qapp):
    """内核不变量（修前即绿）：side 聚焦不改主线 plan/yolo 全局与线程级状态。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        _side_setup(win, rt)
        assert plan_mode.current_mode(state) == "act"  # 全局 mode 键未被 side 碰
        assert permissions.yolo_active(state, "main-1")  # 主线 YOLO 未被清
        assert plan_mode.effective_mode(state, "main-1") == "act"
        assert plan_mode.effective_mode(state, "side-1") == "plan"  # side 强制只读 = 设计意图
    finally:
        cleanup_home(rt._home)


def test_mode_badges_follow_main_when_side_focused(qapp):
    """显示层（修前红）：side 聚焦时全局模式面（徽标 + 菜单勾选）仍显示主线状态。"""
    win, p, rt = _win(qapp)
    try:
        _side_setup(win, rt)
        badge = win.mode_badge.text()
        assert "[Act]" in badge
        assert "[YOLO]" in badge
        assert "[Plan]" not in badge
        assert win.yolo_action.isChecked()  # 勾选态不被 side 清掉
        assert not win.plan_action.isChecked()
    finally:
        cleanup_home(rt._home)


def test_yolo_toggle_while_side_focused_writes_main(qapp):
    """状态写路径（修前红）：side 聚焦时菜单 YOLO 开/关写主线线程，不写 side。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        _side_setup(win, rt)
        win.yolo_action.setChecked(False)  # 用户意图：关主线 YOLO
        assert not permissions.yolo_active(state, "main-1")
        assert not permissions.yolo_active(state, "side-1")  # side 从未有过 YOLO
        win.yolo_action.setChecked(True)  # 镜像：再开也写主线
        assert permissions.yolo_active(state, "main-1")
        assert not permissions.yolo_active(state, "side-1")
    finally:
        cleanup_home(rt._home)


def test_global_plan_on_shows_plan_badge_regardless_of_focus(qapp):
    """全局 plan 开着时：side 聚焦徽标仍显 [Plan]（修前因 side 强制 plan 也绿，
    修后走主线 tid → 全局键——钉住修复没有矫枉过正成 [Act]）。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-1", "main-1")
        win._switch_to("main-1")
        win.plan_action.setChecked(True)  # 全局 plan（写全局键，与焦点无关）
        assert plan_mode.current_mode(state) == "plan"
        win._switch_to("side-1")
        assert "[Plan]" in win.mode_badge.text()
        assert win.plan_action.isChecked()
    finally:
        cleanup_home(rt._home)


def test_close_side_resyncs_badges_to_main(qapp):
    """回归防护：side 关闭回主线后徽标/勾选与主线状态一致（覆盖 _collapse_side_slot 路径）。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        _side_setup(win, rt)
        permissions.side_close(state, "side-1")
        win._switch_to("main-1")
        badge = win.mode_badge.text()
        assert "[Act]" in badge
        assert "[YOLO]" in badge
        assert win.yolo_action.isChecked()
        assert not win.plan_action.isChecked()
    finally:
        cleanup_home(rt._home)
# ---------------------------------------------------------------------------
# gui-ux22 双槽路由修复（Bug 1：侧槽输入错进主线；Bug 2：pill 标错对话）
# ---------------------------------------------------------------------------

def test_side_slot_submit_rejected_without_side_session(qapp):
    """Bug 1：无 side 会话时侧槽提交拒收——不回落到主线，不建 None pane。"""
    win, p, rt = _win(qapp)
    try:
        win._last_side_input_text = "侧槽消息"
        before = set(win.panes.keys())
        win._submit("side")
        assert "还没有侧边会话" in win.side_status.text()
        assert set(win.panes.keys()) == before  # 没长新 pane（含无 None 键）
    finally:
        cleanup_home(rt._home)


def test_side_slot_submit_rejected_when_side_tid_stale(qapp):
    """Bug 1 致因链①：stale side tid（close 路径漏清槽）下侧槽提交拒收，
    且 _slot_tid 不再把失效 tid 泄漏给 start_turn。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-1", "main-1")
        permissions.side_close(state, "side-1")  # 会话已删，但槽 tid 漏清（模拟旧路径）
        win._side_slot_tid = "side-1"
        assert win._slot_tid("side") is None  # stale 兜底：视为无侧边会话
        win._last_side_input_text = "再试"
        win._submit("side")
        assert "还没有侧边会话" in win.side_status.text()
    finally:
        cleanup_home(rt._home)


def test_slash_side_opens_session_in_right_slot(qapp):
    """Bug 2：主槽 /side 开后右槽展开且 side pane 进右栈，pill 可见——
    全在主线程一帧内完成（不再走 worker 跨线程 emit 的错位时序）。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-2", "main-1")
        win._switch_to("main-1")
        p.open_side = lambda tid: ("已开侧边会话 side-2", "side-2")
        win._route_slash("/side", "main")
        assert win._side_slot_tid == "side-2"
        assert win.chat_splitter.sizes()[1] > 0  # 右槽展开
        cur = win.side_stack.currentWidget()
        assert cur is not None and cur.tid == "side-2"  # side pane 在右栈
        assert win.side_pill.isVisibleTo(win)  # pill 在右槽头部可见
    finally:
        cleanup_home(rt._home)


def test_slash_side_close_collapses_slot_and_rejects_next_submit(qapp):
    """侧槽 /side close 成功后：右槽折叠 + stale tid 清掉 + 后续侧槽提交拒收。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-1", "main-1")
        win._switch_to("main-1")
        win._switch_to("side-1")
        assert win._side_slot_tid == "side-1" and win.chat_splitter.sizes()[1] > 0
        p.close_side = lambda tid: ("已关闭侧边会话", "main-1")
        win._route_slash("/side close", "side")
        assert win._side_slot_tid is None
        assert win.chat_splitter.sizes()[1] == 0  # 右槽折叠
        assert not win.side_pill.isVisibleTo(win)
        win._last_side_input_text = "关了还发"
        win._submit("side")
        assert "还没有侧边会话" in win.side_status.text()
    finally:
        cleanup_home(rt._home)


def test_slash_side_close_rejected_keeps_open_slot(qapp):
    """内核拒绝 close（parent 空）时：不误折叠真实开着的右槽，pill 判定也不脱钩。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-1", "main-1")
        win._switch_to("main-1")
        win._switch_to("side-1")
        p.close_side = lambda tid: ("当前不是侧边会话", "")
        win._route_slash("/side close", "side")
        assert win._side_slot_tid == "side-1"  # 槽未清
        assert win.chat_splitter.sizes()[1] > 0  # 未折叠
        assert win.side_pill.isVisibleTo(win)  # pill 跟随右槽持有
    finally:
        cleanup_home(rt._home)


def test_switch_mains_right_slot_follows_side_child(qapp):
    """side 工单 03（修前红）：A→B→C→A 矩阵——主线目标切换时，右槽
    绑该主线的 side child；目标无 side ⇒ 折叠 + 清 stale；重新回到有 side 的
    主线 ⇒ 重新展开并绑其 child（幂等，开/关 side 路径不受影响）。"""
    win, p, rt = _win(qapp)
    try:
        state = rt.permission_state
        permissions.side_open(state, "side-a", "main-a")
        permissions.side_open(state, "side-c", "main-c")
        win._switch_to("main-a")
        assert win._side_slot_tid == "side-a"
        assert win.chat_splitter.sizes()[1] > 0
        win._switch_to("main-b")
        assert win._side_slot_tid is None
        assert win.chat_splitter.sizes()[1] == 0
        win._switch_to("main-c")
        assert win._side_slot_tid == "side-c"
        assert win.chat_splitter.sizes()[1] > 0
        assert win.side_stack.currentWidget() is not None
        assert win.side_stack.currentWidget().tid == "side-c"
        win._switch_to("main-a")
        assert win._side_slot_tid == "side-a"
        assert win.side_stack.currentWidget().tid == "side-a"
    finally:
        cleanup_home(rt._home)
