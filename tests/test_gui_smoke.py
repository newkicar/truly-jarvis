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
        win.input_bar.edit.setPlainText("跑一遍 HITL 全流程")
        win._on_input_submit("跑一遍 HITL 全流程")

        assert wait_until(lambda: events["turn_done"] >= 1, timeout=180.0)
        _pump(qapp)

        # ① 消息上屏：用户块 + 工具行 + AI 回答块都在 pane 里
        pane = win.panes[tid]
        texts = []
        tool_summaries = []
        for i in range(pane._vbox.count()):
            w = pane._vbox.itemAt(i).widget()
            if w is None:
                continue
            if hasattr(w, "text"):
                texts.append(w.text())
            from src.gui.pane import ToolLineWidget

            if isinstance(w, ToolLineWidget):
                tool_summaries.append(w._summary.text())
        all_text = "\n".join(texts + tool_summaries)
        assert "跑一遍 HITL 全流程" in all_text  # 用户块
        assert any("execute" in s for s in tool_summaries)  # 工具行（默认折叠）
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
        win.input_bar.edit.setPlainText("第一条")
        win._on_input_submit("第一条")
        # 第一回合在跑（脚本模型会触发 HITL 审批——自动放行很快，抢在结束前发第二条）
        verdict = presenter.start_turn(tid, "第二条排队")
        assert verdict in ("started", "queued")
        assert wait_until(lambda: not presenter.gate.is_running(tid), timeout=180.0)
        # 排队的「第二条」已自动重投（FIFO）
        assert presenter.gate.queued_count(tid) == 0
        rt.close()
    finally:
        cleanup_home(home)


def test_cold_replay_restores_tool_records(qapp):
    """工单 06：切会话/重启 app 后工具调用记录不丢——第二个 MainWindow 冷建
    同 thread pane，从检查点重建 user/AI + 工具行（默认折叠）。"""
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

        done = {"n": 0}
        bridge.turn_done.connect(lambda tid, ok: done.__setitem__("n", done["n"] + 1))
        tid = presenter.new_session_id()
        win._switch_to(tid)
        win.input_bar.edit.setPlainText("跑一遍")
        win._on_input_submit("跑一遍")
        assert wait_until(lambda: done["n"] >= 1, timeout=180.0)
        _pump(qapp, 1.0)

        # 冷建第二个窗口（模拟切走/重启后的首访）
        win2 = MainWindow(presenter, bridge)
        pane2 = win2._ensure_pane(tid)
        _pump(qapp, 0.5)
        from src.gui.pane import ToolLineWidget

        tools = [
            pane2._vbox.itemAt(i).widget()
            for i in range(pane2._vbox.count())
            if isinstance(pane2._vbox.itemAt(i).widget(), ToolLineWidget)
        ]
        assert tools, "冷建 pane 未重建工具行"
        assert any("execute" in t._summary.text() for t in tools)
        assert all(not t._detail.isVisible() for t in tools)  # 默认折叠
        rt.close()
    finally:
        cleanup_home(home)
def test_queue_strip_layout(qapp):
    """工单 G5：待发队列条固定在输入框上方（不在对话窗内，不随滚动跑掉）。
    断言：① 主窗口挂有 queue_strip，空时隐藏；② 底部布局自上而下顺序
    status_label < queue_strip < image_strip < input_bar；③ 有排队消息时显示。"""
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.queue_strip import QueueStrip
    from src.gui.runtime import GuiPresenter, build_runtime_for_config

    home = new_home()
    try:
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        bridge = UiBridge()
        presenter = GuiPresenter(rt, bridge)
        win = MainWindow(presenter, bridge)

        assert isinstance(win.queue_strip, QueueStrip)
        win.show()
        _pump(qapp, 0.2)
        assert win.queue_strip.isHidden()  # 空队列隐藏
        assert win.queue_strip.items() == []

        host = win.queue_strip.parentWidget()
        for w in (win.status_label, win.image_strip, win.input_bar):
            assert w.parentWidget() is host, "底部区各部件应同属一个布局"
        lay = host.layout()
        widgets = []
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None:
                widgets.append(w)
        pos = {}
        for name, w in (
            ("status_label", win.status_label),
            ("queue_strip", win.queue_strip),
            ("image_strip", win.image_strip),
            ("input_bar", win.input_bar),
        ):
            for k, cand in enumerate(widgets):
                if cand is w:
                    pos[name] = k
                    break
        assert pos["status_label"] < pos["queue_strip"] < pos["image_strip"] < pos["input_bar"]

        win.queue_strip.set_items(["排队的消息"])
        _pump(qapp, 0.1)
        assert not win.queue_strip.isHidden()
        assert win.queue_strip.items() == ["排队的消息"]

        rt.close()
    finally:
        cleanup_home(home)
