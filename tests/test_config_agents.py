"""javis.json agents 段 → 可追加子代理。"""
from dataclasses import replace

import pytest

from conftest import make_fake_config
from src.config_agents import build_config_subagents
from src.permissions import (
    PermissionDenyMiddleware,
    build_permission_deny_middleware,
    build_permission_interrupts,
)
from tests.test_agent import ToolCapableFake


@pytest.fixture
def deny_mw():
    _, state = build_permission_interrupts({})
    return build_permission_deny_middleware(state)


def test_build_config_subagents_appends_valid_agent(deny_mw):
    specs = build_config_subagents(
        {
            "reviewer": {
                "description": "只读代码审查",
                "system_prompt": "你是审查员，只读不写。",
            }
        },
        default_deny_middleware=deny_mw,
    )
    assert len(specs) == 1
    assert specs[0]["name"] == "reviewer"
    assert specs[0]["description"] == "只读代码审查"
    assert "审查员" in specs[0]["system_prompt"]
    assert specs[0]["middleware"] == [deny_mw]


def test_build_config_subagents_skips_reserved_names(deny_mw):
    specs = build_config_subagents(
        {
            "researcher": {"description": "x", "system_prompt": "y"},
            "knowledge_keeper": {"description": "x", "system_prompt": "y"},
            "custom": {"description": "ok", "system_prompt": "prompt"},
        },
        default_deny_middleware=deny_mw,
    )
    assert [s["name"] for s in specs] == ["custom"]


def test_build_config_subagents_skips_incomplete(deny_mw):
    specs = build_config_subagents(
        {
            "bad1": {"description": "only desc"},
            "bad2": {"system_prompt": "only prompt"},
        },
        default_deny_middleware=deny_mw,
    )
    assert specs == []


def test_build_config_subagents_per_agent_permissions(deny_mw):
    specs = build_config_subagents(
        {
            "reviewer": {
                "description": "只读",
                "system_prompt": "只读",
                "permissions": {"write_file": "deny", "edit_file": "deny"},
            }
        },
        default_deny_middleware=deny_mw,
    )
    assert len(specs) == 1
    assert "interrupt_on" in specs[0]
    mw = specs[0]["middleware"][0]
    assert isinstance(mw, PermissionDenyMiddleware)
    assert mw is not deny_mw


def test_build_agent_appends_config_subagents(tmp_path, monkeypatch):
    import src.agent as agent_mod
    from src.agent import build_agent, create_deep_agent

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = replace(
        make_fake_config(tmp_path),
        agents={
            "reviewer": {
                "description": "代码审查",
                "system_prompt": "只读审查。",
            }
        },
    )
    captured = {}

    def spy(**kwargs):
        captured.update(kwargs)
        return create_deep_agent(**kwargs)

    monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
    build_agent(cfg, model=ToolCapableFake(reply="ok"))

    names = {s.get("name") for s in captured.get("subagents", [])}
    assert "reviewer" in names
    assert {"researcher", "knowledge_keeper"} <= names
