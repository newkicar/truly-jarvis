"""gui-ux22 工单 01：GUI 分屏并发预检（双 tid × 并发 graph × 共享 SqliteSaver）。
内核零改动；若暴露并发缺口只补 GUI 层并在 issue 第 4 项记录。自建目录纪律（gui_fakes，不用 tmp_path）。"""
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
            return True
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
            return True
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
            return True
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
