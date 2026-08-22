"""permission hooks 单元测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from src.permission_hooks import (
    hook_matches,
    parse_permission_hooks,
    resolve_permission_hook,
    run_permission_hook,
)
from src.permissions import (
    GATED_TOOLS,
    build_permission_deny_middleware,
    build_permission_interrupts,
)


def test_parse_permission_hooks(tmp_path):
    cfg = {
        "permission": [
            {
                "match": "execute:git push*",
                "command": [sys.executable, "-c", "print('{\"decision\":\"deny\"}')"],
            }
        ]
    }
    rules = parse_permission_hooks(cfg, project_root=tmp_path)
    assert len(rules) == 1
    assert rules[0].match == "execute:git push*"


def test_hook_matches_execute_command():
    from src.permission_hooks import PermissionHookRule

    rule = PermissionHookRule(match="execute:git push*", command=("echo",))
    assert hook_matches(rule, "execute", "git push origin main")
    assert not hook_matches(rule, "execute", "git status")


def test_run_permission_hook_allow_script(tmp_path):
    script = tmp_path / "allow.py"
    script.write_text(
        'import json,sys; print(json.dumps({"decision":"allow"}))',
        encoding="utf-8",
    )
    from src.permission_hooks import PermissionHookRule

    rule = PermissionHookRule(match="*", command=(sys.executable, str(script)))
    decision, _ = run_permission_hook(rule, {"tool": "execute", "path": "git status"})
    assert decision == "allow"


def test_resolve_permission_hook_deny_git_push(tmp_path):
    script = tmp_path / "hook.py"
    script.write_text(
        "import json,sys\n"
        "d=json.load(sys.stdin)\n"
        "p=d.get('path','')\n"
        "if p.startswith('git push'):\n"
        "  print(json.dumps({'decision':'deny','message':'blocked'}))\n"
        "else:\n"
        "  print(json.dumps({'decision':'ask'}))\n",
        encoding="utf-8",
    )
    hooks = {
        "permission": [
            {"match": "execute:git push*", "command": [sys.executable, str(script)]},
        ]
    }
    _, state = build_permission_interrupts({"*": "ask"}, hooks=hooks, project_root=tmp_path)
    hook = resolve_permission_hook(
        state["hooks"],
        "execute",
        {"command": "git push origin main"},
        thread_id="t1",
        project_root=tmp_path,
    )
    assert hook == ("deny", "blocked")


def test_hook_allow_skips_modal_via_action_from_tool_call(tmp_path):
    script = tmp_path / "allow.py"
    script.write_text(
        "import json,sys\n"
        "d=json.load(sys.stdin)\n"
        "if d.get('path','').startswith('git status'):\n"
        "  print(json.dumps({'decision':'allow'}))\n"
        "else:\n"
        "  print(json.dumps({'decision':'ask'}))\n",
        encoding="utf-8",
    )
    hooks = {
        "permission": [
            {"match": "execute:git status*", "command": [sys.executable, str(script)]},
        ]
    }
    interrupt_on, state = build_permission_interrupts({"*": "ask"}, hooks=hooks, project_root=tmp_path)
    when = interrupt_on["execute"]["when"]
    req = type("R", (), {"tool_call": {"name": "execute", "args": {"command": "git status -sb"}}})()
    assert when(req) is False


def test_hook_deny_middleware_returns_error(tmp_path):
    script = tmp_path / "deny.py"
    script.write_text(
        "import json; print(json.dumps({'decision':'deny','message':'nope'}))",
        encoding="utf-8",
    )
    hooks = {
        "permission": [
            {"match": "execute:git push*", "command": [sys.executable, str(script)]},
        ]
    }
    _, state = build_permission_interrupts({"execute": "allow"}, hooks=hooks, project_root=tmp_path)
    mw = build_permission_deny_middleware(state)
    req = type(
        "R",
        (),
        {"tool_call": {"name": "execute", "args": {"command": "git push"}, "id": "tc1"}},
    )()
    result = mw.wrap_tool_call(req, lambda r: "ok")
    assert result.status == "error"
    assert "nope" in result.content


def test_collect_interrupt_decisions_hook_allow():
    from src.streaming import collect_interrupt_decisions

    hooks_cfg = {
        "permission": [
            {
                "match": "execute:git status*",
                "command": [sys.executable, "-c", "print('{\"decision\":\"allow\"}')"],
            }
        ]
    }
    _, state = build_permission_interrupts({"*": "ask"}, hooks=hooks_cfg)
    state["thread_id"] = "t1"
    interrupt = type(
        "I",
        (),
        {
            "value": {
                "action_requests": [
                    {"name": "execute", "args": {"command": "git status -sb"}, "id": "a1"}
                ]
            }
        },
    )()
    called = {"modal": False}

    def ask_action(_inv):
        called["modal"] = True
        return {"decision": "approve"}

    resume = collect_interrupt_decisions([interrupt], ask_action, permission_state=state)
    assert resume == {"decisions": [{"type": "approve"}]}
    assert called["modal"] is False


def test_hook_failure_falls_back_to_ask(tmp_path):
    from src.permission_hooks import PermissionHookRule

    rule = PermissionHookRule(match="*", command=("nonexistent-hook-cmd-xyz",))
    decision, msg = run_permission_hook(rule, {"tool": "execute"})
    assert decision == "ask"
    assert "失败" in msg or "回落" in msg
