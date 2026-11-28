"""goal 核心存储/状态机测试（src.goals）。

Seam: goals.py 公开 API（goal_set/pause/resume/clear/status/complete/mark_budget
/note_turn + should_continue/continuation_decision + 双 prompt + after_turn/AfterTurnResult 收口 + goals.json 存储）
与 src.config 的 goals.max_turns 解析。全部用例显式传 path 或 monkeypatch，
绝不碰真实 ~/.jarvis；目录自建 .scratch/goal-test-tmp（禁 tmp_path/tempfile）。
"""
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from src import goals as g
from src.config import load_config

BASE = Path(__file__).resolve().parent.parent / ".scratch" / "goal-test-tmp"


@contextmanager
def _tmp_dir(name="goals"):
    """自建目录（WinError5 中毒纪律）；调用方负责用 path 参数传 goals.json 位置。"""
    d = BASE / f"{name}-{uuid.uuid4().hex[:8]}"
    os.makedirs(d)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


class _Turn:
    """should_continue 的鸭子类型 turn（.outcome/.tool_calls_count）。"""

    def __init__(self, outcome="ok", tool_calls_count=1):
        self.outcome = outcome
        self.tool_calls_count = tool_calls_count


CTX = {"thread_id": "t1", "plan_mode": False, "pending_interrupt": False}


@pytest.fixture()
def goal_dir():
    with _tmp_dir() as d:
        yield Path(d) / "goals.json"


# ---------------------------------------------------------------- 状态机


def test_goal_set_defaults(goal_dir):
    """set → active，默认 max_turns=5，goal_id=1，turns_used=0。"""
    goal = g.goal_set(path=goal_dir, thread_id="t1", objective="做完 spec 关票")
    assert goal.status == g.GOAL_ACTIVE
    assert goal.goal_id == 1
    assert goal.max_turns == 5
    assert goal.turns_used == 0
    assert goal.completed_at is None
    assert goal.audit_evidence is None


def test_pause_resume_cycle(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    paused = g.goal_pause(path=goal_dir, thread_id="t1")
    assert paused.status == g.GOAL_PAUSED
    active = g.goal_resume(path=goal_dir, thread_id="t1")
    assert active.status == g.GOAL_ACTIVE


def test_double_pause_raises_plain_goal_error(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    g.goal_pause(path=goal_dir, thread_id="t1")
    with pytest.raises(g.GoalError) as exc_info:
        g.goal_pause(path=goal_dir, thread_id="t1")
    assert type(exc_info.value) is g.GoalError


def test_resume_on_active_raises_plain_goal_error(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    with pytest.raises(g.GoalError) as exc_info:
        g.goal_resume(path=goal_dir, thread_id="t1")
    assert type(exc_info.value) is g.GoalError


def test_terminal_pause_resume_mark_raises(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    g.goal_mark_budget_exhausted(path=goal_dir, thread_id="t1")
    for fn in (g.goal_pause, g.goal_resume, g.goal_complete, g.goal_mark_budget_exhausted):
        with pytest.raises(g.TerminalGoalError):
            kwargs = {"audit_evidence": "x"} if fn is g.goal_complete else {}
            fn(path=goal_dir, thread_id="t1", **kwargs)


def test_mutators_without_record_raise_no_goal(goal_dir):
    for fn, kwargs in (
        (g.goal_pause, {}),
        (g.goal_resume, {}),
        (g.goal_clear, {}),
        (g.goal_complete, {"audit_evidence": "x"}),
        (g.goal_mark_budget_exhausted, {}),
        (g.goal_note_turn, {}),
    ):
        with pytest.raises(g.NoGoalError):
            fn(path=goal_dir, thread_id="t9", **kwargs)


def test_goal_clear_returns_goal_then_no_goal(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    deleted = g.goal_clear(path=goal_dir, thread_id="t1")
    assert deleted.objective == "o"
    assert deleted.status == g.GOAL_ACTIVE
    assert g.goal_status(path=goal_dir, thread_id="t1") is None
    with pytest.raises(g.NoGoalError):
        g.goal_clear(path=goal_dir, thread_id="t1")


def test_empty_objective_raises_plain_goal_error(goal_dir):
    with pytest.raises(g.GoalError) as exc_info:
        g.goal_set(path=goal_dir, thread_id="t1", objective="   ")
    assert type(exc_info.value) is g.GoalError


def test_set_on_active_or_paused_raises_exists(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    with pytest.raises(g.GoalExistsError):
        g.goal_set(path=goal_dir, thread_id="t1", objective="again")
    g.goal_pause(path=goal_dir, thread_id="t1")
    with pytest.raises(g.GoalExistsError):
        g.goal_set(path=goal_dir, thread_id="t1", objective="again")


def test_set_on_terminal_raises(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    g.goal_complete(path=goal_dir, thread_id="t1", audit_evidence="evidence")
    with pytest.raises(g.TerminalGoalError):
        g.goal_set(path=goal_dir, thread_id="t1", objective="again")


# ---------------------------------------------------------------- edit (#29)


def test_edit_active_bumps_version_keeps_state(goal_dir):
    """#29: edit = objective 原地替换 + goal_id+1；status/turns_used/max_turns 保留。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="A")
    g.goal_note_turn(path=goal_dir, thread_id="t1")
    edited = g.goal_edit(path=goal_dir, thread_id="t1", objective="B")
    assert edited.objective == "B"
    assert edited.goal_id == 2
    assert edited.status == g.GOAL_ACTIVE
    assert edited.turns_used == 1
    assert edited.max_turns == 5


def test_edit_paused_stays_paused(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="A")
    g.goal_pause(path=goal_dir, thread_id="t1")
    edited = g.goal_edit(path=goal_dir, thread_id="t1", objective="B")
    assert edited.status == g.GOAL_PAUSED
    assert edited.objective == "B"
    assert edited.goal_id == 2


def test_edit_without_record_raises_no_goal(goal_dir):
    with pytest.raises(g.NoGoalError):
        g.goal_edit(path=goal_dir, thread_id="t9", objective="B")


def test_edit_on_complete_raises_terminal(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="A")
    g.goal_complete(path=goal_dir, thread_id="t1", audit_evidence="done")
    with pytest.raises(g.TerminalGoalError):
        g.goal_edit(path=goal_dir, thread_id="t1", objective="B")


def test_edit_on_budget_limited_raises_terminal(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t2", objective="A")
    g.goal_mark_budget_exhausted(path=goal_dir, thread_id="t2")
    with pytest.raises(g.TerminalGoalError):
        g.goal_edit(path=goal_dir, thread_id="t2", objective="B")


def test_edit_stale_version_raises(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="A")
    g.goal_edit(path=goal_dir, thread_id="t1", objective="B", expected_goal_id=1)
    with pytest.raises(g.StaleGoalVersion):
        g.goal_edit(path=goal_dir, thread_id="t1", objective="C", expected_goal_id=1)


def test_edit_blank_objective_raises_plain_goal_error(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="A")
    with pytest.raises(g.GoalError) as exc_info:
        g.goal_edit(path=goal_dir, thread_id="t1", objective="   ")
    assert type(exc_info.value) is g.GoalError
    assert "不能为空" in str(exc_info.value)


def test_change_prompt_renders_untrusted_marker():
    """#29: 续跑变更行 [目标变更]，untrusted 标记（模型当作用户指令读）+ complete_goal 纪律。"""
    text = g.goal_change_prompt(g.Goal("t1", 1, "目标O", g.GOAL_ACTIVE, 1, 3))
    assert text.startswith("[目标变更] ")
    assert "新目标：目标O" in text
    assert "用户指令" in text
    assert "complete_goal" in text


def test_change_prompt_braces_in_objective_no_crash():
    goal = g.Goal("t1", 1, "fix {CI} build", g.GOAL_ACTIVE, 1, 5)
    text = g.goal_change_prompt(goal)
    assert "fix {CI} build" in text


def test_input_label_goal_change_prefix():
    assert g.goal_input_label("[目标变更] 新目标：x") == "目标变更"


def test_input_label_regressions():
    assert g.goal_input_label("[目标续跑 1/5] 自动续跑目标「o」。") == "目标续跑 1/5"
    assert g.goal_input_label("[目标预算耗尽 5/5] 最后一续跑轮") == "目标收尾 5/5"
    assert g.goal_input_label("普通用户消息") is None
    assert g.goal_input_label(None) is None


# ---------------------------------------------------------------- complete


def test_complete_records_evidence_and_timestamp(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    done = g.goal_complete(path=goal_dir, thread_id="t1", audit_evidence="测试 42 全绿")
    assert done.status == g.GOAL_COMPLETE
    assert done.audit_evidence == "测试 42 全绿"
    assert done.completed_at is not None and done.completed_at.endswith("+00:00")


def test_complete_from_paused_ok(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    g.goal_pause(path=goal_dir, thread_id="t1")
    done = g.goal_complete(path=goal_dir, thread_id="t1", audit_evidence="done")
    assert done.status == g.GOAL_COMPLETE


def test_complete_blank_evidence_raises(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    with pytest.raises(g.EvidenceRequiredError):
        g.goal_complete(path=goal_dir, thread_id="t1", audit_evidence="   ")


def test_complete_no_record_blank_evidence_raises_evidence_not_no_goal(goal_dir):
    """evidence 空检查在 _require_record 之前：无记录 + 空证据 → EvidenceRequiredError。"""
    with pytest.raises(g.EvidenceRequiredError):
        g.goal_complete(path=goal_dir, thread_id="t-none", audit_evidence="")


# ---------------------------------------------------------------- note_turn 钳顶


def test_goal_note_turn_clamps_to_max(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=2)
    assert g.goal_note_turn(path=goal_dir, thread_id="t1").turns_used == 1
    assert g.goal_note_turn(path=goal_dir, thread_id="t1").turns_used == 2
    assert g.goal_note_turn(path=goal_dir, thread_id="t1").turns_used == 2


# ---------------------------------------------------------------- goal_id 序列 / 墓碑 / 乐观版本


def test_goal_id_sequence_across_set_clear(goal_dir):
    """goal_id 序列 1→2→3（clear 后 int 墓碑保持 +1 序列）。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="a")
    g.goal_clear(path=goal_dir, thread_id="t1")
    g2 = g.goal_set(path=goal_dir, thread_id="t1", objective="b", expected_goal_id=0)
    assert g2.goal_id == 2
    g.goal_clear(path=goal_dir, thread_id="t1", expected_goal_id=2)
    g3 = g.goal_set(path=goal_dir, thread_id="t1", objective="c")
    assert g3.goal_id == 3


def test_stale_after_clear_tombstone_keeps_version(goal_dir):
    """clear 后墓碑=最后 goal_id：expected=旧 id → Stale；expected=0（无记录哨兵）→ ok。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="a")
    g.goal_clear(path=goal_dir, thread_id="t1")
    with pytest.raises(g.StaleGoalVersion):
        g.goal_set(path=goal_dir, thread_id="t1", objective="b", expected_goal_id=1)
    g2 = g.goal_set(path=goal_dir, thread_id="t1", objective="b", expected_goal_id=0)
    assert g2.goal_id == 2


def test_stale_against_existing_record(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="a")
    g.goal_clear(path=goal_dir, thread_id="t1")
    g.goal_set(path=goal_dir, thread_id="t1", objective="b", expected_goal_id=0)  # 现记录 id=2
    with pytest.raises(g.StaleGoalVersion):
        g.goal_pause(path=goal_dir, thread_id="t1", expected_goal_id=1)


def test_no_record_with_expected_nonzero_stale(goal_dir):
    """全新线程引用了不存在的 goal_id → Stale（不静默覆盖）。"""
    with pytest.raises(g.StaleGoalVersion):
        g.goal_set(path=goal_dir, thread_id="t-new", objective="x", expected_goal_id=7)


def test_cross_thread_tombstones_preserved(goal_dir):
    """其他线程写路径经 raw-map 回写：各自墓碑独立递增。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="a")
    g.goal_set(path=goal_dir, thread_id="t2", objective="b")
    g.goal_clear(path=goal_dir, thread_id="t1")  # t1 墓碑=1
    g.goal_clear(path=goal_dir, thread_id="t2")  # t2 墓碑=1
    g.goal_set(path=goal_dir, thread_id="t2", objective="c", expected_goal_id=0)  # t2 → 2
    g1 = g.goal_set(path=goal_dir, thread_id="t1", objective="d", expected_goal_id=0)
    assert g1.goal_id == 2  # t1 墓碑未被 t2 写路径丢失


# ---------------------------------------------------------------- max_turns 钳制


def test_goal_set_max_turns_clamp_and_fallback(goal_dir):
    assert g.goal_set(path=goal_dir, thread_id="m1", objective="o", max_turns=9).max_turns == 9
    g.goal_clear(path=goal_dir, thread_id="m1")
    assert g.goal_set(path=goal_dir, thread_id="m2", objective="o", max_turns=0).max_turns == 1
    g.goal_clear(path=goal_dir, thread_id="m2")
    assert g.goal_set(path=goal_dir, thread_id="m3", objective="o", max_turns=99999).max_turns == 9999
    g.goal_clear(path=goal_dir, thread_id="m3")
    assert g.goal_set(path=goal_dir, thread_id="m4", objective="o", max_turns="x").max_turns == 5


# ---------------------------------------------------------------- should_continue 全真值表


def _goal(status=g.GOAL_ACTIVE, turns=1, max_turns=5):
    return g.Goal("t1", 1, "o", status, turns, max_turns)


def test_should_continue_all_true():
    assert g.should_continue(_goal(), _Turn("ok", 3), CTX) is True


def test_should_continue_replay_outcome_still_continues():
    """replay 快路径不算断链，照常续。"""
    assert g.should_continue(_goal(), _Turn("replay", 1), CTX) is True


@pytest.mark.parametrize("case", [
    ("none-goal", lambda turn, ctx: g.should_continue(None, turn, ctx), "无 goal"),
    ("paused", lambda turn, ctx: g.should_continue(_goal(status=g.GOAL_PAUSED), turn, ctx), "非 active"),
    ("complete", lambda turn, ctx: g.should_continue(_goal(status=g.GOAL_COMPLETE), turn, ctx), "终态"),
    ("budget-limited", lambda turn, ctx: g.should_continue(_goal(status=g.GOAL_BUDGET_LIMITED), turn, ctx), "终态"),
    ("turns-exhausted", lambda turn, ctx: g.should_continue(_goal(turns=5, max_turns=5), turn, ctx), "预算耗尽"),
    ("cancel", lambda turn, ctx: g.should_continue(_goal(), _Turn("cancel", 1), ctx), "cancel 断链"),
    ("abandon", lambda turn, ctx: g.should_continue(_goal(), _Turn("abandon", 1), ctx), "abandon 断链"),
    ("zero-tools", lambda turn, ctx: g.should_continue(_goal(), _Turn("ok", 0), ctx), "零工具调用"),
    ("plan-mode", lambda turn, ctx: g.should_continue(_goal(), _Turn("ok", 1), {**CTX, "plan_mode": True}), "Plan 模式"),
    ("pending-interrupt", lambda turn, ctx: g.should_continue(_goal(), _Turn("ok", 1), {**CTX, "pending_interrupt": True}), "悬挂 interrupt"),
    ("sched-thread", lambda turn, ctx: g.should_continue(_goal(), _Turn("ok", 1), {**CTX, "thread_id": "sched-123"}), "定时线程"),
])
def test_should_continue_false_table(case):
    name, fn, _why = case
    assert fn(_Turn("ok", 1), CTX) is False, name


# ---------------------------------------------------------------- continuation_decision


def test_decision_none_for_missing_goal():
    d = g.continuation_decision(None, _Turn("ok", 1), CTX)
    assert d.kind == "none" and d.reason and d.prompt is None


def test_decision_continuation_next_turns():
    d = g.continuation_decision(_goal(turns=2, max_turns=5), _Turn("ok", 2), CTX)
    assert d.kind == "continuation"
    assert d.new_turns_used == 3
    assert "3/5" in d.prompt and "complete_goal" in d.prompt


def test_decision_budget_at_last_turn():
    d = g.continuation_decision(_goal(turns=4, max_turns=5), _Turn("ok", 1), CTX)
    assert d.kind == "budget"
    assert d.new_turns_used == 5
    assert "禁止开新工作" in d.prompt


def test_decision_none_when_budget_exhausted():
    d = g.continuation_decision(_goal(turns=5, max_turns=5), _Turn("ok", 1), CTX)
    assert d.kind == "none" and d.reason


# ---------------------------------------------------------------- prompt 渲染


def test_continuation_prompt_renders_discipline():
    text = g.continuation_prompt(_goal(turns=1, max_turns=3), 2)
    assert "2/3" in text
    assert "o" in text
    assert "complete_goal" in text
    assert "微调参数≠换方案" in text
    assert "harness" in text


def test_budget_prompt_renders_handoff():
    text = g.budget_prompt(_goal(turns=4, max_turns=5), 5)
    assert "5/5" in text
    assert "禁止开新工作" in text
    assert "## 已完成" in text and "## 未完成" in text and "## 下一步" in text


# ---------------------------------------------------------------- 存储层


def test_atomic_write_leaves_no_tmp(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="o")
    leftovers = [n for n in os.path.dirname(goal_dir) if n.endswith(".tmp")]
    assert leftovers == []


def test_chinese_objective_stays_readable(goal_dir):
    g.goal_set(path=goal_dir, thread_id="t1", objective="整理周报并归档到 vault")
    raw = goal_dir.read_text(encoding="utf-8")
    assert "整理周报并归档到 vault" in raw


def test_corrupt_goals_file_returns_empty(goal_dir):
    goal_dir.write_text("{bad json", encoding="utf-8")
    assert g.load_goals(goal_dir) == {}


def test_top_level_list_returns_empty(goal_dir):
    goal_dir.write_text("[1, 2]", encoding="utf-8")
    assert g.load_goals(goal_dir) == {}


def test_missing_goals_file_returns_empty(goal_dir):
    assert g.load_goals(goal_dir) == {}


def test_tombstone_values_filtered_by_load_goals(goal_dir):
    """int 墓碑不入 load_goals（状态查询视角 = 无记录），但序列保留。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="a")
    g.goal_clear(path=goal_dir, thread_id="t1")
    assert g.load_goals(goal_dir) == {}
    assert g.goal_status(path=goal_dir, thread_id="t1") is None


def test_goals_path_uses_user_home(monkeypatch):
    home = Path(".scratch/goal-test-tmp/home")
    home.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setattr(g, "user_home", lambda: home)
        assert g.goals_path() == home / g.GOALS_FILENAME
    finally:
        shutil.rmtree(home, ignore_errors=True)


# ---------------------------------------------------------------- config 解析


ENV_OVERRIDES = {
    "BASE_URL": "https://example.com/v1",
    "API_KEY": "sk-test",
    "MODEL_ID": "test-model",
    "TAVILY_KEY": "tvly-test",
}


@pytest.mark.parametrize("goals_section, expected", [
    ({}, 5),
    ({"max_turns": 9}, 9),
    ({"max_turns": 0}, 1),
    ({"max_turns": 99999}, 9999),
    ({"max_turns": "x"}, 5),
])
def test_config_goals_max_turns(goals_section, expected, monkeypatch):
    with _tmp_dir("home") as home, _tmp_dir("proj") as proj:
        monkeypatch.setenv("JARVIS_HOME", str(home))
        json_file = Path(proj) / "jarvis.json"
        data = {"goals": goals_section} if goals_section else {}
        json_file.write_text(json.dumps(data), encoding="utf-8")
        cfg = load_config(json_file=json_file, env_overrides=ENV_OVERRIDES)
        assert cfg.goals_max_turns == expected


def test_config_goals_non_dict_falls_back(monkeypatch):
    """goals 段非 dict → 回落默认 5。"""
    with _tmp_dir("home") as home, _tmp_dir("proj") as proj:
        monkeypatch.setenv("JARVIS_HOME", str(home))
        json_file = Path(proj) / "jarvis.json"
        json_file.write_text(json.dumps({"goals": "boom"}), encoding="utf-8")
        cfg = load_config(json_file=json_file, env_overrides=ENV_OVERRIDES)
        assert cfg.goals_max_turns == 5


# ---------------------------------------------------------------- after_turn 收口


@pytest.fixture()
def _home(goal_dir, monkeypatch):
    """after_turn 无 path 参 → 模块全局 goals_path 隔离到 goal_dir（禁碰真实 ~/.jarvis）。"""
    monkeypatch.setattr(g, "goals_path", lambda: goal_dir)


def test_after_turn_continuation_notes_and_prompts(goal_dir, _home):
    """续跑轮：goal_note_turn 记账 + continuation prompt（前缀 [目标续跑 1/5]），无预算标记。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r = g.after_turn("t1", _Turn(), "干活")
    assert r.kind == "continuation"
    assert r.prompt.startswith("[目标续跑 1/5]")
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 1
    assert r.budget_marked is False


def test_after_turn_budget_decision_clamps(goal_dir, _home):
    """末轮判定 kind=budget（[目标预算耗尽 2/2]），turns_used 钳顶，终态标记留给交接轮。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=2)
    g.goal_note_turn(path=goal_dir, thread_id="t1")
    r = g.after_turn("t1", _Turn(), "干活")
    assert r.kind == "budget"
    assert r.prompt.startswith("[目标预算耗尽 2/2]")
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 2
    assert r.budget_marked is False


def test_after_turn_no_goal_is_none(goal_dir, _home):
    """无目标记录 -> kind=none，prompt 与 budget_marked 均为空。"""
    r = g.after_turn("t1", _Turn(), "干活")
    assert r.kind == "none"
    assert r.prompt is None
    assert r.budget_marked is False


def test_after_turn_cancel_not_counted(goal_dir, _home):
    """cancel 收尾 -> none，不记账（turns_used 保持 0）。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r = g.after_turn("t1", _Turn(outcome="cancel"), "干活")
    assert r.kind == "none"
    assert r.prompt is None
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 0


def test_after_turn_plan_mode_none(goal_dir, _home):
    """Plan 模式 -> none，不记账。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r = g.after_turn("t1", _Turn(), "干活", plan_mode=True)
    assert r.kind == "none"
    assert r.prompt is None
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 0


def test_after_turn_pending_interrupt_none(goal_dir, _home):
    """HITL 悬挂中断 -> none，不记账。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r = g.after_turn("t1", _Turn(), "干活", pending_interrupt=True)
    assert r.kind == "none"
    assert r.prompt is None
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 0


def test_after_turn_inactive_suppresses_but_budget_ungated(goal_dir, _home):
    """active=False：记账与 prompt 双抑制（turns_used 保持 0）；预算终态标记不受 active 门控。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r1 = g.after_turn("t1", _Turn(), "干活", active=False)
    assert r1.kind == "continuation"
    assert r1.prompt is None
    assert r1.budget_marked is False
    assert g.goal_status(path=goal_dir, thread_id="t1").turns_used == 0
    r2 = g.after_turn("t1", _Turn(), "[目标预算耗尽 5/5] 收尾", active=False)
    assert r2.kind == "continuation"
    assert r2.budget_marked is True
    assert g.goal_status(path=goal_dir, thread_id="t1").status == g.GOAL_BUDGET_LIMITED


def test_after_turn_non_str_user_input_skips_budget_marker(goal_dir, _home):
    """user_input 非 str（list）-> 跳过预算标记判定，正常续跑。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)
    r = g.after_turn("t1", _Turn(), ["干活", {"type": "image"}])
    assert r.kind == "continuation"
    assert r.prompt is not None
    assert r.budget_marked is False


def test_after_turn_note_error_swallowed_prompt_kept(goal_dir, _home, monkeypatch):
    """goal_note_turn 抛 GoalError 被吞没，prompt 照常产出（续跑链不断）。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=5)

    def _boom(**_kw):
        raise g.GoalError("存储不可用")

    monkeypatch.setattr(g, "goal_note_turn", _boom)
    r = g.after_turn("t1", _Turn(), "干活")
    assert r.kind == "continuation"
    assert r.prompt.startswith("[目标续跑 1/5]")
    assert r.budget_marked is False


def test_after_turn_terminal_mark_swallowed(goal_dir, _home):
    """终态 goal：kind=none（非 active 不续），预算标记吞没 TerminalGoalError。"""
    g.goal_set(path=goal_dir, thread_id="t1", objective="o", max_turns=2)
    g.goal_mark_budget_exhausted(path=goal_dir, thread_id="t1")
    r = g.after_turn("t1", _Turn(), "[目标预算耗尽 2/2] 收尾")
    assert r.kind == "none"
    assert r.prompt is None
    assert r.budget_marked is False


def test_after_turn_no_record_budget_prefix_swallowed(goal_dir, _home):
    """无 goal 记录：kind=none，预算标记吞没 NoGoalError，budget_marked 仍 False。"""
    r = g.after_turn("t9", _Turn(), "[目标预算耗尽 1/1] 收尾")
    assert r.kind == "none"
    assert r.prompt is None
    assert r.budget_marked is False

