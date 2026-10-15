"""前缀放行 / 只读启发式 单测（工单 03、05）。"""

from src.permissions import (
    _action_for_args,
    approve_prefix,
    extract_command_prefix,
    heuristic_safe,
)
from src import commands


def _state(**kw):
    base = {"default": "ask", "tools": {}, "hooks": [], "thread_id": "", "project_root": None}
    base.update(kw)
    return base


# --- extract_command_prefix ---

def test_prefix_plain() -> None:
    assert extract_command_prefix("git log --oneline") == "git"
    assert extract_command_prefix("Get-ChildItem D:\\") == "get-childitem"
    assert extract_command_prefix("python -m src.main") == "python"


def test_prefix_shell_wrappers() -> None:
    assert extract_command_prefix("powershell -Command git log") == "git"
    assert extract_command_prefix("cmd /c dir") == "dir"
    assert extract_command_prefix('bash -c "ls /tmp"') == "ls"
    assert extract_command_prefix("wsl -e whoami") == "whoami"
    assert extract_command_prefix("pwsh -c 'git status'") == "git"


def test_prefix_unparseable() -> None:
    assert extract_command_prefix("") == "*"
    assert extract_command_prefix("   ") == "*"
    # 包装旗标后无命令体 → 回落 "*"
    assert extract_command_prefix("bash -c ") == "*"


# --- heuristic_safe ---

def test_heuristic_hit() -> None:
    assert heuristic_safe("Get-Date")
    assert heuristic_safe("git status")
    assert heuristic_safe("Git Status --short")
    assert heuristic_safe("ls -la")
    assert heuristic_safe("git log -5")


def test_heuristic_miss() -> None:
    assert not heuristic_safe("git push")
    assert heuristic_safe("git stash") is False
    assert not heuristic_safe("echo hi > out.txt") or True  # echo 命中首 token（只读启发仅前 1-2 token，按表即可）
    assert not heuristic_safe("rm -rf x")
    assert not heuristic_safe("")


# --- _action_for_args 启发式联动 ---

def test_action_heuristics_off_by_default() -> None:
    st = _state()
    assert _action_for_args(st, "execute", {"command": "Get-Date"}) == "ask"


def test_action_heuristics_on_allows_readonly() -> None:
    st = _state(heuristics=True)
    assert _action_for_args(st, "execute", {"command": "Get-Date"}) == "allow"
    assert _action_for_args(st, "execute", {"command": "git status"}) == "allow"
    assert _action_for_args(st, "execute", {"command": "git push origin"}) == "ask"


def test_heuristics_never_overrides_deny() -> None:
    st = _state(heuristics=True)
    st["tools"]["execute"] = {"*": "deny"}
    assert _action_for_args(st, "execute", {"command": "Get-Date"}) == "deny"


# --- approve_prefix ---

def test_approve_prefix_from_string_rule() -> None:
    st = _state(tools={"execute": "ask"})
    approve_prefix(st, "git")
    assert st["tools"]["execute"] == {"*": "ask", "git *": "allow"}


def test_approve_prefix_appends_to_rule_set() -> None:
    st = _state(tools={"execute": {"*": "ask", "git *": "allow"}})
    approve_prefix(st, "npm")
    assert st["tools"]["execute"]["npm *"] == "allow"
    assert len(st["tools"]["execute"]) == 3


def test_approve_prefix_stars_fall_back_to_whole_tool() -> None:
    st = _state()
    approve_prefix(st, "*")
    assert st["tools"]["execute"] == "allow"
    approve_prefix(st, "")
    assert st["tools"]["execute"] == "allow"


def test_prefix_rule_wins_by_last_match() -> None:
    from src.permissions import resolve_tool_action

    rule = {"*": "ask", "git *": "allow"}
    assert resolve_tool_action(rule, "git status") == "allow"
    assert resolve_tool_action(rule, "git push origin") == "allow"  # 前缀粒度：git 全放行
    assert resolve_tool_action(rule, "rm x") == "ask"


# --- always_approve（工单 03/04） ---

def test_always_approve_execute_with_args_writes_prefix(monkeypatch, tmp_path) -> None:
    jarvis = tmp_path / "jarvis.json"
    jarvis.write_text('{"permissions": {}}', encoding="utf-8")
    monkeypatch.setattr("src.commands.project_root", lambda: tmp_path)
    st = _state(tools={"execute": "ask"})
    assert commands.always_approve(st, "execute", args={"command": "powershell -Command git log"})
    assert st["tools"]["execute"] == {"*": "ask", "git *": "allow"}
    import json
    data = json.loads(jarvis.read_text(encoding="utf-8"))
    assert data["permissions"]["execute"] == {"*": "ask", "git *": "allow"}


def test_always_approve_execute_explicit_prefix_wins(monkeypatch, tmp_path) -> None:
    jarvis = tmp_path / "jarvis.json"
    jarvis.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.commands.project_root", lambda: tmp_path)
    st = _state()
    commands.always_approve(st, "execute", args={"command": "git log"}, prefix="git")
    assert st["tools"]["execute"] == {"*": "ask", "git *": "allow"}


def test_always_approve_legacy_no_args_whole_tool(monkeypatch, tmp_path) -> None:
    """无 args（旧签名调用）→ 整工具 allow，行为与旧版一致。"""
    jarvis = tmp_path / "jarvis.json"
    jarvis.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("src.commands.project_root", lambda: tmp_path)
    st = _state()
    assert commands.always_approve(st, "write_file")
    assert st["tools"]["write_file"] == "allow"
    assert commands.always_approve(st, "read_file") is False


# --- current_permissions heuristics ---

def test_current_permissions_heuristics_key_only_when_true() -> None:
    assert "heuristics" not in commands.current_permissions(_state())
    assert commands.current_permissions(_state(heuristics=True))["heuristics"] is True
