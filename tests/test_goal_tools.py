"""tests/test_goal_tools.py — 票 04：模型侧 goal 工具 ×3（create_goal/complete_goal/get_goal）。

目录纪律：.scratch/goal-tool-test-tmp/<uuid> + os.makedirs，fixture 末尾 rmtree；
禁 tmp_path/tempfile（WinError5 中毒预存红族）。
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

import pytest

from src import goals
from src.goal_tools import build_goal_tools

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRATCH = os.path.join(_ROOT_DIR, ".scratch", "goal-tool-test-tmp")

_GOAL_TOOL_NAMES = {"create_goal", "complete_goal", "get_goal"}


@pytest.fixture()
def goals_env(monkeypatch):
    """自建 scratch 目录做 goals.json 落盘点（不走 ~/.jarvis）。"""
    base = os.path.join(_SCRATCH, uuid.uuid4().hex[:12])
    os.makedirs(base, exist_ok=True)
    from src.permissions import build_permission_interrupts

    _interrupt_on, state = build_permission_interrupts(None, project_root=Path(base))
    state["thread_id"] = "test-thread-1"
    yield {"base": base, "goals_path": os.path.join(base, "goals.json"), "state": state}
    shutil.rmtree(base, ignore_errors=True)


def _tools(goals_env, default_max_turns=None):
    by_name = {}
    for t in build_goal_tools(goals_env["state"], goals_path=goals_env["goals_path"], default_max_turns=default_max_turns):
        by_name[t.name] = t
    assert set(by_name) == _GOAL_TOOL_NAMES
    return by_name


def _disk(goals_env, tid="test-thread-1"):
    p = goals_env["goals_path"]
    if not os.path.isfile(p):
        return None
    raw = json.loads(open(p, encoding="utf-8").read())
    return raw.get(tid)


# ① create 成功 shape：返回文本 + 盘上核对
def test_create_goal_success_shape(goals_env):
    tools = _tools(goals_env)
    out = tools["create_goal"].invoke({"objective": "修完三处 bug"})
    assert "目标已创建（#1）" in out
    assert "修完三处 bug" in out
    assert "进行中" in out
    assert "回合预算：0/5" in out
    rec = _disk(goals_env)
    assert rec is not None
    assert rec["goal_id"] == 1
    assert rec["status"] == "active"
    assert rec["max_turns"] == 5
    assert rec["turns_used"] == 0


# ② 重复 create（预置 active）→ 文本含「在途目标」
def test_create_goal_rejected_when_active(goals_env):
    goals.goal_set(path=goals_env["goals_path"], thread_id="test-thread-1", objective="已有目标")
    tools = _tools(goals_env)
    out = tools["create_goal"].invoke({"objective": "再来一个"})
    assert "在途目标" in out
    assert _disk(goals_env)["objective"] == "已有目标"  # 原记录未被覆盖


# ③ 终态 create → 文本含「已终态」
def test_create_goal_rejected_when_terminal(goals_env):
    goals.goal_set(path=goals_env["goals_path"], thread_id="test-thread-1", objective="旧目标")
    goals.goal_complete(path=goals_env["goals_path"], thread_id="test-thread-1", audit_evidence="证据")
    tools = _tools(goals_env)
    out = tools["create_goal"].invoke({"objective": "新目标"})
    assert "已终态" in out


# ④ complete 空白证据 → 文本含「必须附审计证据」且盘上 status 仍 active
def test_complete_goal_requires_evidence(goals_env):
    goals.goal_set(path=goals_env["goals_path"], thread_id="test-thread-1", objective="目标")
    tools = _tools(goals_env)
    out = tools["complete_goal"].invoke({"audit_evidence": "   "})
    assert "必须附审计证据" in out
    assert _disk(goals_env)["status"] == "active"


# ⑤ complete 成功 → 盘上 status=complete / audit_evidence / completed_at 非空
def test_complete_goal_success(goals_env):
    goals.goal_set(path=goals_env["goals_path"], thread_id="test-thread-1", objective="目标")
    tools = _tools(goals_env)
    out = tools["complete_goal"].invoke({"audit_evidence": "pytest 956 全绿"})
    assert "目标已标记完成（#1）" in out
    rec = _disk(goals_env)
    assert rec["status"] == "complete"
    assert rec["audit_evidence"] == "pytest 956 全绿"
    assert rec["completed_at"]


# ⑥ get 无 goal → 「本会话无目标」；有 goal → 多行含 objective/状态/回合数/剩余
def test_get_goal_none_and_present(goals_env):
    tools = _tools(goals_env)
    assert "本会话无目标" in tools["get_goal"].invoke({})
    goals.goal_set(path=goals_env["goals_path"], thread_id="test-thread-1", objective="做四件事", max_turns=8)
    goals.goal_note_turn(path=goals_env["goals_path"], thread_id="test-thread-1")
    out = tools["get_goal"].invoke({})
    assert "做四件事" in out
    assert "进行中" in out
    assert "回合：1/8" in out
    assert "剩余预算：7" in out


# ⑦ permission_state=None → 三工具均返缺 thread_id 友好文本，不抛
def test_tools_without_permission_state(goals_env):
    for t in build_goal_tools(None):
        out = t.invoke({"objective": "x", "audit_evidence": "y"} if t.name != "get_goal" else {})
        assert "缺少 thread_id" in out


# ⑧ 子代理 spec 不含 goal 工具
def test_subagent_specs_exclude_goal_tools(goals_env):
    from src.config_agents import build_config_subagents
    from src.subagents import build_knowledge_keeper, build_researcher

    r = build_researcher()
    assert "tools" in r
    assert not _GOAL_TOOL_NAMES & {getattr(t, "name", "") for t in r["tools"]}

    k = build_knowledge_keeper()
    assert "tools" not in k  # 继承主代理后端默认工具，无显式 tools 键

    specs = build_config_subagents(
        {"my_agent": {"description": "d", "system_prompt": "s"}},
        default_deny_middleware=None,
    )
    assert len(specs) == 1
    assert "tools" not in specs[0]


# ⑨ build_agent 注入契约：主代理 tools 含 3 个 goal 工具（MCP 同款位）
def test_build_agent_injects_goal_tools(goals_env, monkeypatch):
    import src.agent as agent_mod
    from src.agent import create_deep_agent
    from tests.conftest import make_fake_config
    from tests.test_agent import ToolCapableFake

    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    base = goals_env["base"]
    ws = Path(base) / "ws"
    os.makedirs(ws, exist_ok=True)
    cfg = make_fake_config(ws)
    agent_mod.build_agent(cfg, model=ToolCapableFake(reply="ok"), permission_state=goals_env["state"])
    names = {getattr(t, "name", "") for t in captured.get("tools", [])}
    assert _GOAL_TOOL_NAMES <= names


# ⑩ default_max_turns 透传：工厂传 7、create 不传 → 盘上 max_turns == 7
def test_default_max_turns_passthrough(goals_env):
    tools = _tools(goals_env, default_max_turns=7)
    tools["create_goal"].invoke({"objective": "目标"})
    assert _disk(goals_env)["max_turns"] == 7
