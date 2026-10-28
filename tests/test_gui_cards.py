"""工单 04 — HITL 审批卡片：四按钮/编辑表单/放弃 + 与 resume 契约同构。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton

from tests.gui_fakes import cleanup_home, new_home, ScriptedMockModel
from tests.test_gui_presenter import wait_until


def _inv(name="execute", args=None, path=None):
    from src import commands

    return commands.ToolInvocation(name=name, args=args or {"command": "echo hi"}, path=path)


def _card(inv, out):
    from src.gui.cards import ApprovalCard

    c = ApprovalCard(inv, "echo hi", lambda r: out.append(r), lambda: out.append(None))
    return c


# ---- widget 级（不碰 agent）
def test_approve_emits_decision(qtbot):
    out: list = []
    card = _card(_inv(), out)
    qtbot.addWidget(card)
    card.btn_approve.click()
    assert out == [{"decision": "approve"}]
    assert card._locked


def test_reject_then_locked(qtbot):
    out: list = []
    card = _card(_inv(), out)
    qtbot.addWidget(card)
    card.btn_reject.click()
    assert out == [{"decision": "reject"}]
    # 决策后按钮锁死，再点无效
    card.btn_approve.click()
    assert out == [{"decision": "reject"}]


def test_abandon_returns_none(qtbot):
    out: list = []
    card = _card(_inv(), out)
    qtbot.addWidget(card)
    card.btn_giveup.click()
    assert out == [None]


def test_edit_params_blank_keeps_original(qtbot):
    inv = _inv("write_file", {"file_path": "a.txt", "content": "old\n"})
    out: list = []
    card = _card(inv, out)
    qtbot.addWidget(card)
    card._open_editor()
    ok_btn = card._editor_box.findChild(QPushButton)
    assert ok_btn is not None
    ok_btn.click()
    assert out and out[0]["decision"] == "edit"
    assert out[0]["edited"]["file_path"] == "a.txt"  # 留空保留原值
    assert out[0]["edited"]["content"] == "old\n"


def test_always_approve_non_execute_is_whole_tool(qtbot):
    inv = _inv("write_file", {"file_path": "a.txt", "content": "x"})
    out: list = []
    card = _card(inv, out)
    qtbot.addWidget(card)
    card.btn_always.click()
    assert out == [{"decision": "always_approve"}]


def test_always_approve_execute_has_prefix_editor(qtbot):
    from PySide6.QtWidgets import QLineEdit

    inv = _inv("execute", {"command": "git status"})
    out: list = []
    card = _card(inv, out)
    qtbot.addWidget(card)
    card.btn_always.click()
    assert card._prefix_edit.text() == "git"  # 默认前缀（extract_command_prefix）
    card._prefix_edit.setText("git log")
    ok = card.findChild(QPushButton)
    # 「确认永久放行」按钮
    for b in card.findChildren(QPushButton):
        if "确认" in b.text():
            b.click()
            break
    assert out and out[0]["decision"] == "always_approve"
    assert out[0]["prefix"] == "git log"


# ---- 全链路：真实卡片 + 脚本 mock（拒绝→改道→放行）
def test_full_reject_reroute_approve_chain(qapp):
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import build_runtime_for_config

    home = new_home()
    try:
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        bridge = UiBridge()
        from src.gui.presenter_wiring import wire_presenter

        presenter = wire_presenter(rt, bridge)  # 默认内联审批卡片
        win = MainWindow(presenter, bridge)

        finished = {"ok": False}
        bridge.turn_done.connect(lambda tid, ok: finished.__setitem__("ok", ok))

        tid = presenter.new_session_id()
        win._switch_to(tid)
        win.input_bar.edit.setPlainText("拒绝 execute，看改道")
        win._on_input_submit("拒绝 execute，看改道")

        # 阶段 1：execute 卡片 → 点「拒绝」
        card1 = _wait_card(win, tid, "execute")
        card1.btn_reject.click()

        # 阶段 2：mock 改道 write_file 卡片 → 点「放行」
        card2 = _wait_card(win, tid, "write_file")
        card2.btn_approve.click()

        assert wait_until(lambda: finished["ok"], timeout=180.0)
        qapp.processEvents()

        # 文件已写（write_file 走真实 backend）
        hello = home / "hello.txt"
        assert hello.is_file() and "jarvis gui" in hello.read_text(encoding="utf-8")
        rt.close()
    finally:
        cleanup_home(home)


def test_abandon_card_stops_turn(qapp):
    """放弃本轮：卡片「放弃」→ 回合以放弃结束（ok=False），工具未执行。"""
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import build_runtime_for_config

    home = new_home()
    try:
        rt = build_runtime_for_config(home, model=ScriptedMockModel())
        bridge = UiBridge()
        from src.gui.presenter_wiring import wire_presenter

        presenter = wire_presenter(rt, bridge)
        win = MainWindow(presenter, bridge)
        finished = {"done": 0, "ok": None}

        def _done(tid, ok):
            finished["done"] += 1
            finished["ok"] = ok

        bridge.turn_done.connect(_done)

        tid = presenter.new_session_id()
        win._switch_to(tid)
        win.input_bar.edit.setPlainText("放弃试试")
        win._on_input_submit("放弃试试")
        card = _wait_card(win, tid, "execute")
        card.btn_giveup.click()
        assert wait_until(lambda: finished["done"] >= 1, timeout=180.0)
        assert finished["ok"] is False
        assert not (home / "hello.txt").exists()  # execute 被放弃，未执行
        rt.close()
    finally:
        cleanup_home(home)


# ---------------------------------------------------------------- 辅助
def _wait_card(win, tid, name, timeout=120.0):
    import time

    from PySide6.QtWidgets import QApplication

    from src.gui.cards import ApprovalCard

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    pane = win.panes[tid]
    while time.monotonic() < deadline:
        app.processEvents()
        for i in range(pane._vbox.count()):
            w = pane._vbox.itemAt(i).widget()
            if isinstance(w, ApprovalCard) and not w._locked and w._inv.name == name:
                return w
        time.sleep(0.02)
    raise AssertionError(f"未等到 {name} 卡片")


# ---------------------------------------------------------------- 卡片宽度（2026-10-28 报障）
def test_card_min_width_does_not_blow_up(qtbot):
    """审批卡片最小宽不得被长内容顶爆（旧版 600 字符 preview → 7843px 最小宽，
    把会话面板/主窗口撑出屏幕）。长 preview/长 path/长原值 后卡片最小宽
    仍由按钮行主导（< 400px）。"""
    from src.gui.cards import ApprovalCard

    out: list = []
    inv = _inv("execute", {"command": " ".join(["powershell -NoProfile -Command " + "x" * 60] * 8)})
    card = ApprovalCard(inv, "y" * 600, lambda r: out.append(r), lambda: out.append(None))
    qtbot.addWidget(card)
    assert card.minimumSizeHint().width() < 400

    inv2 = _inv("write_file", {"file_path": "a.txt", "content": "z" * 500}, path="D:" + "/deep/path" * 30)
    card2 = ApprovalCard(inv2, "w" * 600, lambda r: out.append(r), lambda: out.append(None))
    qtbot.addWidget(card2)
    assert card2.minimumSizeHint().width() < 400


def test_card_fits_narrow_pane(qtbot):
    """窄面板（600px）内卡片宽度收在面板内，不溢出（面板不再被卡片撑宽）。"""
    from src.gui.pane import ChatPane

    pane = ChatPane("t-narrow")
    qtbot.addWidget(pane)
    pane.append_card(_card(_inv("execute", {"command": "k" * 600}), []))
    pane.resize(600, 400)
    pane.show()
    assert pane.widget().width() <= 600


def test_soft_break_splits_long_tokens():
    from src.gui.cards import _soft_break

    assert _soft_break("a" * 100, 30).count("\n") == 3
    assert _soft_break("短", 30) == "短"
    assert _soft_break("行1\n" + "b" * 70, 30) == "行1\n" + "b" * 30 + "\n" + "b" * 30 + "\n" + "b" * 10
