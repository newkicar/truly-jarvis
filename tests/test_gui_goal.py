"""#goal 06: GUI 目标自动续跑接线（turn finally 决策入 TurnGate FIFO + 弹头重投 + 预算后置终态）。

Seam: GuiPresenter._turn_worker finally（monkeypatch streaming.run_agent_turn，offscreen Qt，
不碰真实模型）+ src.goals 存储。goals.json 落盘点自建目录（tmp_path WinError 5 中毒纪律）。
"""
import os
import shutil
import time
import uuid
import pytest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src import goals, streaming
from src.gui.events import UiBridge
from src.gui.runtime import GuiPresenter

BASE = Path(__file__).resolve().parent.parent / ".scratch" / "gui-goal-tmp"


@pytest.fixture()
def bridge(qapp) -> UiBridge:
    return UiBridge()


def _fake_runtime():
    from tests.gui_fakes import new_home

    home = new_home()
    cfg = SimpleNamespace(
        project_root=home,
        execution_max_steps=200,
        model_image_input="auto",
        mcps={},
        vault_path=None,
        memory_dir=home / ".jarvis" / "memory",
        schedules_dir=home / "schedules",
        api_key="sk-fake",
        base_url="https://fake.example/v1",
        model_id="fake-model",
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="bge-small-zh-v1.5",
        checkpoint_db=home / ".jarvis" / "checkpoints" / "checkpoints.sqlite",
    )
    rt = SimpleNamespace(agent=None, config=cfg, permission_state={}, model_label="fake")
    rt.mcp_tool_count = 0
    from src.gui.runtime import SchedulerGate

    rt.gate = SchedulerGate(rt, enabled=False)
    rt._home = home
    return rt


def wait_until(cond, timeout: float = 8.0) -> bool:
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


@pytest.fixture()
def goal_store(monkeypatch):
    base = str(BASE / uuid.uuid4().hex[:12])
    os.makedirs(base, exist_ok=True)
    target = Path(base) / "goals.json"
    monkeypatch.setattr(goals, "goals_path", lambda: target)
    yield target
    shutil.rmtree(base, ignore_errors=True)


def _fake_chain_stop(monkeypatch, calls):
    """续跑轮（user_input 以 [目标 开头）零工具调用 → 链条自然停止，避免 5 轮连环。"""

    def fake(agent, tid, user_input, **kw):
        text = str(user_input)
        calls.append(text)
        if text.startswith("[目标"):
            return streaming.TurnOutcome(True, "complete", 0, None)
        return streaming.TurnOutcome(True, "complete", 1, None)

    monkeypatch.setattr(streaming, "run_agent_turn", fake)
    return fake


# ---------- ① 续跑：原始任务轮 finally 入队 → 弹头重投自动第二回合 ----------
def test_gui_continuation_auto_second_turn(bridge, qapp, monkeypatch, goal_store):
    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    tid = "g1"
    goals.goal_set(thread_id=tid, objective="修好 CI", max_turns=5)
    calls = []
    _fake_chain_stop(monkeypatch, calls)
    assert p.start_turn(tid, "原始任务") == "started"
    assert wait_until(lambda: len(calls) == 2 and not p.gate.is_running(tid))
    assert calls[0] == "原始任务"
    assert calls[1].startswith("[目标续跑 1/5]") and "修好 CI" in calls[1]
    g = goals.goal_status(thread_id=tid)
    assert g.turns_used == 1 and g.status == goals.GOAL_ACTIVE


# ---------- ② 预算收尾轮：入队后跑完 → 后置 budget_limited 终态 ----------
def test_gui_budget_terminal_post_mark(bridge, qapp, monkeypatch, goal_store):
    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    tid = "g2"
    goals.goal_set(thread_id=tid, objective="o", max_turns=2)
    goals.goal_note_turn(thread_id=tid)  # 剩 1 轮 = 收尾轮
    calls = []
    _fake_chain_stop(monkeypatch, calls)
    assert p.start_turn(tid, "原始任务") == "started"
    assert wait_until(lambda: len(calls) == 2 and not p.gate.is_running(tid))
    assert calls[1].startswith("[目标预算耗尽 2/2]")
    g = goals.goal_status(thread_id=tid)
    assert g.turns_used == 2 and g.status == goals.GOAL_BUDGET_LIMITED


# ---------- ③ 无 goal：单轮即停 ----------
def test_gui_no_goal_single_turn(bridge, qapp, monkeypatch, goal_store):
    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    tid = "g3"
    calls = []
    _fake_chain_stop(monkeypatch, calls)
    assert p.start_turn(tid, "普通消息") == "started"
    assert wait_until(lambda: len(calls) == 1 and not p.gate.is_running(tid))
    assert calls == ["普通消息"]
    assert p.gate.queued_texts(tid) == []
    assert goals.goal_status(thread_id=tid) is None


# ---------- ④ cancel 断链：单轮、不记账 ----------
def test_gui_cancel_breaks_chain(bridge, qapp, monkeypatch, goal_store):
    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    tid = "g4"
    goals.goal_set(thread_id=tid, objective="o", max_turns=5)
    calls = []

    def fake(agent, tid2, user_input, **kw):
        calls.append(str(user_input))
        return streaming.TurnOutcome(True, "cancel", 1, None)

    monkeypatch.setattr(streaming, "run_agent_turn", fake)
    assert p.start_turn(tid, "原始任务") == "started"
    assert wait_until(lambda: len(calls) == 1 and not p.gate.is_running(tid))
    g = goals.goal_status(thread_id=tid)
    assert g.turns_used == 0 and g.status == goals.GOAL_ACTIVE


# ---------- ⑤ 零工具调用：单轮、不记账 ----------
def test_gui_zero_tools_single_turn(bridge, qapp, monkeypatch, goal_store):
    rt = _fake_runtime()
    p = GuiPresenter(rt, bridge)
    tid = "g5"
    goals.goal_set(thread_id=tid, objective="o", max_turns=5)
    calls = []

    def fake(agent, tid2, user_input, **kw):
        calls.append(str(user_input))
        return streaming.TurnOutcome(True, "complete", 0, None)

    monkeypatch.setattr(streaming, "run_agent_turn", fake)
    assert p.start_turn(tid, "原始任务") == "started"
    assert wait_until(lambda: len(calls) == 1 and not p.gate.is_running(tid))
    g = goals.goal_status(thread_id=tid)
    assert g.turns_used == 0 and g.status == goals.GOAL_ACTIVE


import pytest
