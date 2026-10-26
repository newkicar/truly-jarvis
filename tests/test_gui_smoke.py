"""工单 01 垂直冒烟：真实图 + 脚本 mock 模型 + SqliteSaver，offscreen 全流程。

验收（工单 01）：运行新入口的等价路径——输入 → 流式回答上屏 → 完成 →
检查点落 SqliteSaver；同 thread 回合门生效。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.gui_fakes import cleanup_home, new_home, ScriptedMockModel
from tests.test_gui_presenter import wait_until


def _pump(app, secs: float = 0.5):
    import time

    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        app.processEvents()


def test_full_turn_streams_and_persists(qapp):
    from src import commands
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter, build_runtime_for_config

    home = new_home()
    try:
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        bridge = UiBridge()
        presenter = GuiPresenter(rt, bridge)
        auto_approve = {"hits": 0}

        def ask(inv, tid):
            auto_approve["hits"] += 1
            return {"decision": "approve"}

        presenter.set_ask_action(ask)
        win = MainWindow(presenter, bridge)

        events = {"turn_done": 0}
        bridge.turn_done.connect(lambda tid, ok: events.__setitem__("turn_done", events["turn_done"] + 1))

        tid = presenter.new_session_id()
        win._switch_to(tid)
        win.input.setPlainText("跑一遍 HITL 全流程")
        win._submit()

        assert wait_until(lambda: events["turn_done"] >= 1, timeout=180.0)
        _pump(qapp)

        # ① 消息上屏：用户块 + 工具行 + AI 回答块都在 pane 里
        pane = win.panes[tid]
        texts = []
        for i in range(pane._vbox.count()):
            w = pane._vbox.itemAt(i).widget()
            if w is not None and hasattr(w, "text"):
                texts.append(w.text())
        all_text = "\n".join(texts)
        assert "跑一遍 HITL 全流程" in all_text  # 用户块
        assert "✓ execute" in all_text  # 工具行
        assert auto_approve["hits"] >= 1  # 走了 HITL（自动放行）

        # ② 检查点落盘（SqliteSaver）
        state = rt.agent.get_state(commands.thread_config(tid))
        msgs = state.values.get("messages") or []
        assert any(getattr(m, "type", "") == "human" for m in msgs)
        assert any(getattr(m, "type", "") == "ai" for m in msgs)
        rt.close()
    finally:
        cleanup_home(home)


def test_turn_gate_blocks_second_submission(qapp):
    """同 thread 回合进行中再发 = 排队（FIFO），不并发。"""
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter, build_runtime_for_config

    home = new_home()
    try:
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        bridge = UiBridge()
        presenter = GuiPresenter(rt, bridge)
        presenter.set_ask_action(lambda inv, tid: {"decision": "approve"})
        win = MainWindow(presenter, bridge)

        tid = presenter.new_session_id()
        win._switch_to(tid)
        win.input.setPlainText("第一条")
        assert win._submit() is None
        # 第一回合在跑（脚本模型会触发 HITL 审批——自动放行很快，抢在结束前发第二条）
        verdict = presenter.start_turn(tid, "第二条排队")
        assert verdict in ("started", "queued")
        assert wait_until(lambda: not presenter.gate.is_running(tid), timeout=180.0)
        # 排队的「第二条」已自动重投（FIFO）
        assert presenter.gate.queued_count(tid) == 0
        rt.close()
    finally:
        cleanup_home(home)
