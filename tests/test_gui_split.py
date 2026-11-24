"""gui-ux22 工单 01；工单 02：QSplitter 双槽布局回归（开=展开/关=折叠/pane re-parent/手柄拖动）。
工单 01 内核零改动；若暴露并发缺口只补 GUI 层并在 issue 第 4 项记录。自建目录纪律（gui_fakes，不用 tmp_path）。"""
import json, os, threading, time, types
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import commands, streaming
from src.gui.events import UiBridge
from src.gui.main_window import MainWindow
from src.gui.runtime import GuiPresenter, build_runtime_for_config
from tests.gui_fakes import ScriptedMockModel, cleanup_home, new_home
from tests.test_gui_presenter import wait_until

MAIN, SIDE = "session-m", "side-s"  # tid[:10] 即整 tid，worker 线程名可精确断言


class _FakeInterrupt:
    def __init__(self, tid):
        self.value = {"action_requests": [
            {"name": "execute", "args": {"command": f"echo {tid}"}, "id": f"call-{tid}"}]}


class _SlowScriptedModel(ScriptedMockModel):
    def _stream(self, messages, stop=None, run_manager=None, **kw):
        for c in super()._stream(messages, stop, run_manager, **kw):
            time.sleep(0.03)
            yield c


def test_dual_tid_concurrent_no_deadlock(qapp, monkeypatch):
    home = new_home(); rt = None
    try:
        monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        p = GuiPresenter(rt, UiBridge())
        records = {}; blocked = {}; barrier = threading.Barrier(2, timeout=30)
        def fake_run(agent, tid, user_input, **kw):
            records[tid] = {"start": threading.current_thread().name}
            try: barrier.wait(30)
            except threading.BrokenBarrierError: blocked[tid] = True
            kw["callbacks"]["on_message_delta"]("A" if tid == MAIN else "B")
            kw["callbacks"]["on_message_end"]("AB")
            records[tid]["finish"] = threading.current_thread().name
            return streaming.TurnOutcome(True, "complete", 1, None)
        monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
        assert p.start_turn(MAIN, "m") == "started"
        assert p.start_turn(SIDE, "s") == "started"
        assert wait_until(lambda: not p._turns, 60.0)
        assert not blocked, blocked
        assert records[MAIN]["start"] == "jarvis-gui-turn-session-m"
        assert records[SIDE]["start"] == "jarvis-gui-turn-side-s"
        assert records[MAIN]["start"] != records[SIDE]["start"]
        assert records[MAIN]["start"] == records[MAIN]["finish"]
        assert records[SIDE]["start"] == records[SIDE]["finish"]
        assert wait_until(lambda: not p.gate.is_running(MAIN) and not p.gate.is_running(SIDE), 30.0)
    finally:
        if rt is not None: rt.close()
        cleanup_home(home)


def test_hitl_routes_by_tid(qapp, monkeypatch):
    home = new_home(); rt = None
    try:
        monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        p = GuiPresenter(rt, UiBridge())
        records = {}; barrier = threading.Barrier(2, timeout=30)
        def fake_run(agent, tid, user_input, **kw):
            barrier.wait(30)
            records[tid] = kw["handle_interrupts"]([_FakeInterrupt(tid)])
            return streaming.TurnOutcome(True, "complete", 1, None)
        monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
        asks = {MAIN: [], SIDE: []}
        def ask(inv, tid):
            asks[tid].append((inv.name, inv.path)); return {"decision": "approve"}
        p.set_ask_action(ask)
        assert p.start_turn(MAIN, "m") == "started"
        assert p.start_turn(SIDE, "s") == "started"
        assert wait_until(lambda: not p._turns, 60.0)
        assert records[MAIN] == {"decisions": [{"type": "approve"}]}
        assert records[SIDE] == {"decisions": [{"type": "approve"}]}
        assert asks[MAIN] == [("execute", "echo session-m")]
        assert asks[SIDE] == [("execute", "echo side-s")]
        assert "call-side-s" not in json.dumps(records[MAIN])
        assert "call-session-m" not in json.dumps(records[SIDE])
    finally:
        if rt is not None: rt.close()
        cleanup_home(home)


def test_queue_status_route_by_tid_and_sched_regression(qapp, monkeypatch):
    home = new_home(); rt = None; win = None
    try:
        monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        p = GuiPresenter(rt, UiBridge())
        gates = {MAIN: threading.Event(), SIDE: threading.Event()}
        def fake_run(agent, tid, user_input, **kw):
            gates[tid].wait(60)
            kw["callbacks"]["on_message_delta"]("ok")
            kw["callbacks"]["on_message_end"]("ok")
            return streaming.TurnOutcome(True, "complete", 1, None)
        monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
        assert p.start_turn(MAIN, "first-m") == "started"
        assert p.start_turn(SIDE, "first-s") == "started"
        assert p.start_turn(MAIN, "q1") == "queued"
        assert p.start_turn(SIDE, "q9") == "queued"
        assert p.gate.queued_texts(MAIN) == ["q1"]
        assert p.gate.queued_texts(SIDE) == ["q9"]
        bridge = p.bridge; flushes = []
        bridge.queued_flush.connect(lambda tid, text, imgs: flushes.append((tid, text)))
        gates[MAIN].set()
        assert wait_until(lambda: flushes and flushes[0] == (MAIN, "q1"), 60.0)
        assert all(t == MAIN for t, _ in flushes)
        gates[SIDE].set()
        assert wait_until(lambda: (SIDE, "q9") in flushes, 60.0)
        assert wait_until(
            lambda: not p._turns and not p.gate.is_running(MAIN) and not p.gate.is_running(SIDE)
            and p.gate.queued_count(MAIN) == 0 and p.gate.queued_count(SIDE) == 0, 60.0)
        # GUI 层：状态行仅写 active 槽；sched-* 卡片入 pane 不崩（回归）
        win = MainWindow(p, bridge)
        win._switch_to(MAIN); win.status_label.setText("就绪")
        win._on_status(SIDE, "运行中"); assert win.status_label.text() == "就绪"
        win._on_status(MAIN, "运行中"); assert win.status_label.text() == "运行中"
        win._on_status("sched-x", "定时运行中"); assert win.status_label.text() == "运行中"
        payload = (types.SimpleNamespace(name="execute", path="echo sched"), "preview", "c1", lambda r: None, lambda: None)
        win._on_create_card("sched-x", payload, "c1"); assert "sched-x" in win.panes
        win.close()
    finally:
        if rt is not None: rt.close()
        cleanup_home(home)


def test_real_graph_dual_concurrent_sqlite_persist(qapp, monkeypatch):
    home = new_home(); rt = None
    try:
        monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
        rt = build_runtime_for_config(home, model=_SlowScriptedModel())
        p = GuiPresenter(rt, UiBridge())
        p.set_ask_action(lambda inv, tid: {"decision": "approve"})
        done = []
        p.bridge.turn_done.connect(lambda tid, ok: done.append((tid, ok)))
        main_tid = p.new_session_id()
        assert p.start_turn(main_tid, "跑一遍 HITL 全流程") == "started"
        assert wait_until(lambda: any(t == main_tid for t, _ in done), 180.0)
        assert done[-1] == (main_tid, True)
        note, side_tid = p.open_side(main_tid)
        assert side_tid and p.is_side(side_tid) and not p.is_side(main_tid)
        fin_calls = []; real = commands.finalize_turn
        def spy(agent, thread_id):
            fin_calls.append((thread_id, threading.current_thread().name)); return real(agent, thread_id)
        monkeypatch.setattr(commands, "finalize_turn", spy)
        assert p.start_turn(main_tid, "主线第二轮") == "started"
        assert p.start_turn(side_tid, "侧线任务") == "started"
        assert wait_until(lambda: len([d for d in done if d[0] in (main_tid, side_tid)]) == 3, 180.0)
        assert all(ok for t, ok in done if t in (main_tid, side_tid))
        by_tid = {}
        for t, th in fin_calls: by_tid[t] = th
        assert by_tid.get(main_tid) == f"jarvis-gui-turn-{main_tid[:10]}"
        assert by_tid.get(side_tid) == f"jarvis-gui-turn-{side_tid[:10]}"
        mstate = rt.agent.get_state(commands.thread_config(main_tid)).values["messages"]
        sstate = rt.agent.get_state(commands.thread_config(side_tid)).values["messages"]
        assert any(getattr(m, "type", "") == "human" for m in mstate)
        assert any(getattr(m, "type", "") == "ai" for m in mstate)
        assert any(getattr(m, "type", "") == "human" for m in sstate)
        assert any(getattr(m, "type", "") == "ai" for m in sstate)
    finally:
        if rt is not None: rt.close()
        cleanup_home(home)


# ---------------------------------------------------------------- 工单 02：QSplitter 双槽布局
# 开 side = 右槽展开 / 关 side = 右槽折叠 / pane 按槽归属 re-parent / 手柄原生拖动。
# side 开/关走轻路径（permissions.side_open + 拦截 commands.close_side），不 fork graph。


def _win_with_side(qapp, monkeypatch):
    """真 runtime + MainWindow + 一主线 + 一 side。返回 (home, rt, p, win, tid, side_tid)。"""
    from PySide6.QtWidgets import QMessageBox
    import src.commands as commands_mod
    from src import permissions

    home = new_home()
    rt = build_runtime_for_config(home, model=ScriptedMockModel())
    p = GuiPresenter(rt, UiBridge())
    monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
    win = MainWindow(p, p.bridge)
    tid = p.new_session_id()
    side_tid = p.new_session_id()
    p.session_registry.rename(tid, "主线")
    p.session_registry.rename(side_tid, "主线-side")
    monkeypatch.setattr(p, "session_ids", lambda: [tid, side_tid])
    permissions.side_open(rt.permission_state, side_tid, tid)
    monkeypatch.setattr(
        commands_mod, "close_side",
        lambda agent, t, state: ("已删除 side 会话并返回主线 " + tid, tid),
    )
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )
    return home, rt, p, win, tid, side_tid


def test_splitter_open_side_expands(qapp, monkeypatch):
    """开 side：右槽展开半宽；双槽四件套各自独立实例；pane 按槽归属 re-parent。"""
    home, rt, p, win, tid, side_tid = _win_with_side(qapp, monkeypatch)
    try:
        win._switch_to(tid)        # 先主线：确保双 pane 均创建
        win._switch_to(side_tid)
        win.show()
        qapp.processEvents()
        sizes = win.chat_splitter.sizes()
        assert len(sizes) == 2 and sizes[0] > 0 and sizes[1] > 0
        # 双槽四件套独立实例（左槽保持旧属性名，右槽新实例）
        assert win.side_input_bar is not win.input_bar
        assert win.side_image_strip is not win.image_strip
        assert win.side_queue_strip is not win.queue_strip
        assert win.side_status is not win.status_label
        # pane re-parent：各槽当前 pane 落进自己的栈
        assert win.panes[side_tid].parentWidget() is win.side_stack
        assert win.panes[tid].parentWidget() is win.stack
        assert win.side_stack.currentWidget() is win.panes[side_tid]
        assert win.stack.currentWidget() is win.panes[tid]
        assert win.active_tid == side_tid
        assert not win.side_pill.isHidden()
    finally:
        rt.close()
        win.close()
        cleanup_home(home)


def test_splitter_close_side_collapses(qapp, monkeypatch):
    """关 side（pill）：右槽折叠 0 宽、回主线、左槽布局回归旧单列等价。"""
    home, rt, p, win, tid, side_tid = _win_with_side(qapp, monkeypatch)
    try:
        win._switch_to(tid)        # 先主线：确保双 pane 均创建
        win._switch_to(side_tid)
        win.show()
        qapp.processEvents()
        assert win.chat_splitter.sizes()[1] > 0
        win._on_side_pill_clicked()  # 关 = 删 side 回主线（close_side 已拦截）
        qapp.processEvents()
        assert win.chat_splitter.sizes()[1] == 0
        assert win.active_tid == tid
        assert win.side_pill.isHidden()
        assert win.stack.currentWidget() is win.panes[tid]
        # 左槽四件套同宿主 + 自上而下顺序（旧单列布局等价回归）
        host = win.status_label.parentWidget()
        for w in (win.queue_strip, win.image_strip, win.input_bar):
            assert w.parentWidget() is host
        lay = host.layout()
        widgets = [lay.itemAt(i).widget() for i in range(lay.count())]
        widgets = [w for w in widgets if w is not None]
        pos = {}
        for name, w in (("status_label", win.status_label),
                        ("queue_strip", win.queue_strip),
                        ("image_strip", win.image_strip),
                        ("input_bar", win.input_bar)):
            for k, cand in enumerate(widgets):
                if cand is w:
                    pos[name] = k
                    break
        assert pos["status_label"] < pos["queue_strip"] < pos["image_strip"] < pos["input_bar"]
        # 右槽四件套 + pill 同属右槽宿主（折叠 0 宽但布局完整）
        rhost = win.side_status.parentWidget()
        assert rhost is not host
        for w in (win.side_pill, win.side_queue_strip, win.side_image_strip, win.side_input_bar):
            assert w.parentWidget() is rhost
    finally:
        rt.close()
        win.close()
        cleanup_home(home)


def test_pane_reparent_across_switches(qapp, monkeypatch):
    """主/侧反复切换：pane 实例常驻（id 不变）、按槽归属 re-parent、dirty flush 不崩。"""
    home, rt, p, win, tid, side_tid = _win_with_side(qapp, monkeypatch)
    try:
        win._switch_to(tid)        # 先主线：确保双 pane 均创建
        win._switch_to(side_tid)
        pane_s, pane_m = win.panes[side_tid], win.panes[tid]
        id_s, id_m = id(pane_s), id(pane_m)
        for _ in range(3):
            win._switch_to(side_tid)
            qapp.processEvents()
            win._flush_all_dirty()
            win._switch_to(tid)
            qapp.processEvents()
            # re-parent 只跟槽归属不跟 active：side pane 始终在右槽
            assert pane_s.parentWidget() is win.side_stack
            assert pane_m.parentWidget() is win.stack
            win._flush_all_dirty()
        assert id(win.panes[side_tid]) == id_s
        assert id(win.panes[tid]) == id_m
    finally:
        rt.close()
        win.close()
        cleanup_home(home)


def test_splitter_no_side_stays_collapsed(qapp, monkeypatch):
    """无 side：右槽恒 0 宽（现状单列布局回归）；右槽部件在但 0 宽。"""
    home = new_home()
    rt = build_runtime_for_config(home, model=ScriptedMockModel())
    p = GuiPresenter(rt, UiBridge())
    monkeypatch.setattr(GuiPresenter, "_maybe_name", lambda self, tid, ok: None)
    win = MainWindow(p, p.bridge)
    try:
        tid = p.new_session_id()
        p.session_registry.rename(tid, "主线")
        monkeypatch.setattr(p, "session_ids", lambda: [tid])
        win._switch_to(tid)
        win.show()
        qapp.processEvents()
        assert win.chat_splitter.sizes()[1] == 0
        assert win.side_pill.isHidden()
        host = win.status_label.parentWidget()
        for w in (win.queue_strip, win.image_strip, win.input_bar):
            assert w.parentWidget() is host
        assert win.side_status.parentWidget() is not host
    finally:
        rt.close()
        win.close()
        cleanup_home(home)


def test_splitter_handle_drag_ratio(qapp, monkeypatch):
    """手柄原生拖动面：handle 存在；setSizes 比例读回保持（offscreen 不断言绝对像素）。"""
    home, rt, p, win, tid, side_tid = _win_with_side(qapp, monkeypatch)
    try:
        win._switch_to(tid)        # 先主线：确保双 pane 均创建
        win._switch_to(side_tid)
        win.show()
        qapp.processEvents()
        assert win.chat_splitter.handle(1) is not None  # 原生手柄：用户可自由拖动
        win.chat_splitter.setSizes([100, 400])
        qapp.processEvents()
        s = win.chat_splitter.sizes()
        assert s[1] > s[0]  # 1:4 比例读回（右槽占大头）
    finally:
        rt.close()
        win.close()
        cleanup_home(home)
