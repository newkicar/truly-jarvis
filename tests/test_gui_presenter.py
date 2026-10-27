"""工单 01 — GuiPresenter：worker→主线程事件契约 + 回合门 + 取消 + FIFO 重投。

offscreen Qt + fake run_agent_turn（monkeypatch streaming 层）——不碰真实模型。
"""
import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src import streaming
from src.gui.events import UiBridge


@pytest.fixture()
def bridge(qapp) -> UiBridge:
    return UiBridge()


def _fake_runtime():
    """lightweight runtime stub（回合 worker 只用 agent/config/permission_state；
    session_registry 需要真 project_root → 建个 home 目录）。"""
    from pathlib import Path  # noqa: F401

    from tests.gui_fakes import new_home

    home = new_home()
    cfg = SimpleNamespace(
        project_root=home,
        execution_max_steps=200,
        model_image_input="auto",
    )
    rt = SimpleNamespace(agent=None, config=cfg, permission_state={}, model_label="fake")
    rt._home = home
    return rt


def wait_until(cond, timeout: float = 5.0) -> bool:
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_turn_worker_emits_event_contract(bridge, qapp, monkeypatch):
    from src.gui.runtime import GuiPresenter

    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    seen = {"deltas": [], "tool": [], "turn_done": [], "turn_started": []}
    monkeypatch.setattr(
        streaming,
        "run_agent_turn",
        lambda agent, tid, user_input, **kw: (
            kw["callbacks"]["on_message_delta"]("部分回答"),
            kw["callbacks"]["on_message_delta"]("（完）"),
            kw["callbacks"]["on_tool_call"]("execute", "{'command': 'x'}", False, "ok", 0),
            True,
        )[3],
    )
    bridge.message_delta.connect(lambda tid, d: seen["deltas"].append((tid, d)))
    bridge.tool_call.connect(lambda tid, n, a, e, o, dp: seen["tool"].append((tid, n, a, e, o, dp)))
    bridge.turn_started.connect(lambda tid: seen["turn_started"].append(tid))
    bridge.turn_done.connect(lambda tid, ok: seen["turn_done"].append((tid, ok)))

    assert p.start_turn("t1", "你好") == "started"
    assert wait_until(lambda: seen["turn_done"])

    assert ("t1", "部分回答") in seen["deltas"]
    assert ("t1", "（完）") in seen["deltas"]
    assert ("t1", "execute", "{'command': 'x'}", False, "ok", 0) in seen["tool"]
    assert seen["turn_started"] == ["t1"]
    assert seen["turn_done"] == [("t1", True)]


def test_queueing_and_fifo_replay(bridge, qapp, monkeypatch):
    from src.gui.runtime import GuiPresenter

    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    calls: list[str] = []
    release = threading.Event()

    def fake_run(agent, tid, user_input, **kw):
        calls.append(str(user_input))
        if len(calls) == 1:
            release.wait(timeout=5.0)
        return True

    monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
    assert p.start_turn("t1", "m1") == "started"
    assert p.start_turn("t1", "m2") == "queued"
    assert p.start_turn("t1", "m3") == "queued"
    assert p.gate.queued_count("t1") == 2
    release.set()
    assert wait_until(lambda: len(calls) == 3 and not p.gate.is_running("t1"))
    assert calls == ["m1", "m2", "m3"]  # FIFO 顺序重投
    assert p.gate.queued_count("t1") == 0


def test_cancel_sets_gate_flag(bridge, qapp, monkeypatch):
    from src.gui.runtime import GuiPresenter

    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)

    def fake_run(agent, tid, user_input, **kw):
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline and not kw["is_cancelled"]():
            time.sleep(0.01)
        return False

    monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
    p.start_turn("t1", "x")
    p.cancel("t1")
    assert p.gate.is_cancelled("t1")
    assert wait_until(lambda: not p.gate.is_running("t1"), timeout=8.0)


def test_default_ask_rejects_and_notifies(bridge, qapp, monkeypatch):
    from src.gui.runtime import GuiPresenter

    p = GuiPresenter(_fake_runtime(), bridge)
    inv = SimpleNamespace(name="execute", args={"command": "x"}, path=None)
    notes: list[str] = []
    bridge.notify.connect(notes.append)
    result = p._default_ask(inv, "t9")
    assert result == {"decision": "reject"}
    qapp.processEvents()
    assert any("需审批" in n for n in notes)


def test_thread_isolation(bridge, qapp, monkeypatch):
    """跨 thread 并行：a 在跑时 b 可立即进回合。"""
    from src.gui.runtime import GuiPresenter

    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    calls: list[str] = []
    release = threading.Event()

    def fake_run(agent, tid, user_input, **kw):
        calls.append(tid)
        release.wait(timeout=5.0)
        return True

    monkeypatch.setattr(streaming, "run_agent_turn", fake_run)
    assert p.start_turn("a", "x") == "started"
    assert p.start_turn("b", "y") == "started"  # 不同 thread 不排队
    release.set()
    assert wait_until(lambda: not p.gate.is_running("a") and not p.gate.is_running("b"))
    assert set(calls) == {"a", "b"}
