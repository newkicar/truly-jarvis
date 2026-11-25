"""diagnosing-bugs /goal 四缺陷修复回归：链断裂留痕 + create/resume 重启手柄 + GUI 目标徽标。

- active 断链（零工具轮等）→ last_stop_reason 留痕 + goal_text「已停」尾注
- active-broken 的 /goal resume → 重启文案（存储层 goal_resume 仍显式报错，语义不变）
- goal_kick_prompt = create/resume 链重启手柄（纯只读；status/pause/clear/裸/无目标/
  非 active/预算耗尽 → None）
- goal_note_turn 清 last_stop_reason（续跑链活着 = 停止原因作废）
- 旧 JSON 无键向后兼容
- GUI 静态翻转断言（_refresh_mode_badges / _execute_slash 含 goal 处理）
"""
import json
import os
import re
import shutil
import uuid
from pathlib import Path

import pytest

from src import commands, goals, streaming

BASE = Path(__file__).resolve().parent.parent / ".scratch" / "goal-chain-fix-tmp"
TID = "goal-chain-fix"


@pytest.fixture()
def goal_store(monkeypatch):
    base = str(BASE / uuid.uuid4().hex[:12])
    os.makedirs(base, exist_ok=True)
    target = Path(base) / "goals.json"
    monkeypatch.setattr(goals, "goals_path", lambda: target)
    yield target
    shutil.rmtree(base, ignore_errors=True)


def _work_turn(outcome: str = "complete", tools: int = 1) -> streaming.TurnOutcome:
    return streaming.TurnOutcome(True, outcome, tools, None)


def test_zero_tool_active_turn_persists_stop_reason(goal_store):
    """缺陷1：零工具轮 jarvis 停（断链）→ last_stop_reason 留痕 + 状态行尾注。"""
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    res = goals.after_turn(TID, _work_turn(tools=0), "干活")
    assert res.kind == "none"
    g = goals.goal_status(thread_id=TID)
    assert g.status == goals.GOAL_ACTIVE
    assert g.last_stop_reason == "该轮零工具调用"
    text = commands.goal_text(TID)
    assert "已停" in text
    assert "零工具调用" in text
    assert "重启" in text


def test_active_broken_resume_restarts_chain(goal_store):
    """缺陷2：active-broken 的 /goal resume → 重启文案；goal_kick_prompt 给出链重启手柄。"""
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    goals.after_turn(TID, _work_turn(tools=0), "干活")
    out = commands.goal_command_text(TID, "/goal resume")
    assert "重新开跑" in out
    kick = commands.goal_kick_prompt(TID, "/goal resume")
    assert kick is not None
    assert kick.startswith("[目标续跑 1/5]")
    assert "修好 CI" in kick


def test_create_success_kick(goal_store):
    """缺陷1+3：create 成功后 /goal create 也附续跑 prompt（kick 1/n），jarvis 不会停了就停。"""
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    kick = commands.goal_kick_prompt(TID, "/goal 修好 CI")
    assert kick is not None
    assert kick.startswith("[目标续跑 1/5]")


def test_kick_none_variants(goal_store):
    """goal_kick_prompt → None：status/pause/clear/裸/无目标/paused/预算耗尽/终态/已清除。"""
    assert commands.goal_kick_prompt(TID, "/goal status") is None
    assert commands.goal_kick_prompt(TID, "/goal pause") is None
    assert commands.goal_kick_prompt(TID, "/goal clear") is None
    assert commands.goal_kick_prompt(TID, "/goal") is None
    assert commands.goal_kick_prompt("fresh-tid", "/goal 干活") is None
    # paused
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    goals.goal_pause(thread_id=TID)
    assert commands.goal_kick_prompt(TID, "/goal resume") is None
    # 预算耗尽
    goals.goal_set(thread_id="exhausted", objective="o", max_turns=1)
    goals.after_turn("exhausted", _work_turn(tools=1), "续跑")
    assert commands.goal_kick_prompt("exhausted", "/goal resume") is None
    # 终态
    goals.goal_set(thread_id="done", objective="o", max_turns=5)
    goals.goal_complete(thread_id="done", audit_evidence="pytest 全绿")
    assert commands.goal_kick_prompt("done", "/goal resume") is None
    # 已清除
    goals.goal_set(thread_id="cleared", objective="o", max_turns=5)
    goals.goal_clear(thread_id="cleared")
    assert commands.goal_kick_prompt("cleared", "/goal 干活") is None


def test_note_turn_clears_stop_reason(goal_store):
    """续跑链活着 = last_stop_reason 作废：正常续跑一轮后 goal_text 不再有「已停」尾注。"""
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    goals.after_turn(TID, _work_turn(tools=0), "干活")
    assert goals.goal_status(thread_id=TID).last_stop_reason is not None
    res = goals.after_turn(TID, _work_turn(tools=1), "继续干活")
    assert res.kind == "continuation"
    g = goals.goal_status(thread_id=TID)
    assert g.last_stop_reason is None
    assert "已停" not in commands.goal_text(TID)
    assert g.turns_used == 1


def test_old_json_without_last_stop_reason_key(goal_store):
    """向后兼容：旧版 goals.json 无 last_stop_reason 键 → from_dict 为 None 不崩。"""
    data = {
        TID: {
            "thread_id": TID,
            "goal_id": 1,
            "objective": "修好 CI",
            "status": "active",
            "turns_used": 0,
            "max_turns": 5,
        }
    }
    goal_store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    g = goals.goal_status(thread_id=TID)
    assert g is not None
    assert g.last_stop_reason is None
    assert commands.goal_kick_prompt(TID, "/goal resume") is not None


def test_storage_resume_on_active_still_raises(goal_store):
    """存储层语义不变：active 下 goal_resume 仍显式报错（red-loop ② 回归）。"""
    goals.goal_set(thread_id=TID, objective="修好 CI", max_turns=5)
    with pytest.raises(goals.GoalError, match="已 active"):
        goals.goal_resume(thread_id=TID)


def test_gui_source_goal_flip():
    """缺陷4：GUI 静态翻转断言（徽标 + /goal 常驻状态行 + kick 重启）。"""
    text = (
        Path(__file__).resolve().parent.parent / "src" / "gui" / "main_window.py"
    ).read_text(encoding="utf-8")
    m = re.search(r"def _refresh_mode_badges\(self\).*?(?=\n    _BADGE_STATES)", text, re.S)
    assert m is not None
    assert "goal" in m.group(0).lower()
    m2 = re.search(r"def _execute_slash\(.*?(?=\n    def _on_scheduler_panel)", text, re.S)
    assert m2 is not None
    assert "goal" in m2.group(0).lower()
