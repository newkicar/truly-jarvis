"""#goal 06: CLI 目标自动续跑接线（_cli_goal_step 纯判定 + _stream_turn while 续跑 + 预算后置终态）。

Seam: src.main._cli_goal_step / _stream_turn（monkeypatch streaming.run_agent_turn，
不碰真实模型）+ src.goals 存储。goals.json 落盘点自建目录（tmp_path WinError 5 中毒纪律）。
"""
import os
import shutil
import uuid
from pathlib import Path

import pytest

import src.main as m
from src import goals, streaming
from src.streaming import TurnOutcome

BASE = os.path.join(os.getcwd(), ".scratch", "goal-cli-tmp")


@pytest.fixture()
def goal_store(monkeypatch):
    base = os.path.join(BASE, uuid.uuid4().hex[:12])
    os.makedirs(base, exist_ok=True)
    target = Path(base) / "goals.json"
    monkeypatch.setattr(goals, "goals_path", lambda: target)
    yield target
    shutil.rmtree(base, ignore_errors=True)


def _turn(ok=True, outcome="complete", tools=1):
    return TurnOutcome(ok, outcome, tools, None)


# ---------- ① 续跑轮：note 记账 + 打印目标行 + 返回续跑 prompt ----------
def test_cli_continuation_notes_and_returns_prompt(goal_store, capsys):
    goals.goal_set(thread_id="t1", objective="修好 CI", max_turns=5)
    prompt = m._cli_goal_step("t1", "原始任务", _turn(), None)
    assert prompt.startswith("[目标续跑 1/5]") and "修好 CI" in prompt
    out = capsys.readouterr().out
    assert "目标 [进行中] 1/5" in out
    g = goals.goal_status(thread_id="t1")
    assert g.turns_used == 1 and g.status == goals.GOAL_ACTIVE


# ---------- ② 预算收尾轮：返回收尾 prompt + 后置 budget_limited 终态 ----------
def test_cli_budget_round_marks_terminal(goal_store, capsys):
    goals.goal_set(thread_id="t2", objective="o", max_turns=2)
    goals.goal_note_turn(thread_id="t2")  # turns_used=1，剩余 1 轮 = 收尾轮
    prompt = m._cli_goal_step("t2", "[目标预算耗尽 2/2] 收尾", _turn(), None)
    assert prompt.startswith("[目标预算耗尽 2/2]")
    g = goals.goal_status(thread_id="t2")
    assert g.turns_used == 2 and g.status == goals.GOAL_BUDGET_LIMITED


def _setup_complete():
    goals.goal_set(thread_id="tx", objective="o", max_turns=5)
    goals.goal_complete(thread_id="tx", audit_evidence="e")


def _setup_budget_limited():
    goals.goal_set(thread_id="tx", objective="o", max_turns=5)
    goals.goal_mark_budget_exhausted(thread_id="tx")


# ---------- ③ 不续跑矩阵：全部返回 None 且不记账 ----------
@pytest.mark.parametrize(
    "case, setup",
    [
        ("no_goal", lambda: None),
        ("zero_tools", lambda: goals.goal_set(thread_id="tx", objective="o", max_turns=5)),
        ("cancel", lambda: goals.goal_set(thread_id="tx", objective="o", max_turns=5)),
        ("complete", _setup_complete),
        ("budget_limited", _setup_budget_limited),
    ],
)
def test_cli_no_continuation_matrix(goal_store, case, setup):
    setup()
    turn = _turn(tools=0 if case == "zero_tools" else 1)
    if case == "cancel":
        turn = _turn(outcome="cancel")
    if case in ("complete", "budget_limited"):
        pass  # 终态 goal 已就位，turn 形态无关
    assert m._cli_goal_step("tx", "原始任务", turn, None) is None
    if case != "no_goal":
        assert goals.goal_status(thread_id="tx").turns_used == 0


# ---------- ④ 全链：原始任务 → 续跑 1/2 → 收尾 2/2 → 停（3 轮 fake 调用）----------
def test_cli_stream_turn_full_chain(goal_store, monkeypatch, capsys):
    goals.goal_set(thread_id="t3", objective="o", max_turns=2)
    calls = []

    def fake(agent, tid, user_input, **kw):
        calls.append(str(user_input))
        return TurnOutcome(True, "complete", 1, None)

    monkeypatch.setattr(streaming, "run_agent_turn", fake)
    m._stream_turn(None, "t3", "任务", None, None)
    assert len(calls) == 3
    assert calls[0] == "任务"
    assert calls[1].startswith("[目标续跑 1/2]")
    assert calls[2].startswith("[目标预算耗尽 2/2]")
    g = goals.goal_status(thread_id="t3")
    assert g.turns_used == 2 and g.status == goals.GOAL_BUDGET_LIMITED
