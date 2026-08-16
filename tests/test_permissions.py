"""审批权限模块测试（src.permissions）。

Seam: build_permission_interrupts / resolve_tool_action / apply_permission_override
/ dump_permissions_json。验证配置→interrupt_on 映射、规则集匹配、always approve
的运行时可变引用 + 持久化。
"""
import json

from src.permissions import (
    GATED_TOOLS,
    apply_permission_override,
    build_permission_interrupts,
    dump_permissions_json,
    resolve_tool_action,
)


def test_default_all_ask():
    """不配置 permissions 时，所有 gated tool 默认 ask（每次审批）。"""
    interrupt_on, state = build_permission_interrupts({})
    assert "execute" in interrupt_on
    assert "write_file" in interrupt_on
    assert "edit_file" in interrupt_on
    assert "delete" in interrupt_on
    assert state["default"] == "ask"
    assert interrupt_on["execute"]["allowed_decisions"] == ["approve", "reject"]
    assert interrupt_on["edit_file"]["allowed_decisions"] == ["approve", "reject", "edit"]


def test_allow_auto_approves():
    """allow = 不中断（interrupt_on False）。"""
    interrupt_on, _ = build_permission_interrupts({"execute": "allow"})
    assert interrupt_on["execute"] is False
    assert interrupt_on["write_file"] is not False  # 其他仍 ask


def test_ruleset_last_match_wins():
    """规则集形态：最后匹配胜出（opencode 语义）。"""
    rule = {"*": "ask", "git *": "allow", "git push *": "deny"}
    assert resolve_tool_action(rule, "git status") == "allow"
    assert resolve_tool_action(rule, "git push origin main") == "deny"
    assert resolve_tool_action(rule, "rm -rf /") == "ask"
    assert resolve_tool_action(rule, "ls") == "ask"


def test_when_predicate_reads_runtime_state():
    """when 谓词闭包引用 state，改 state 立即生效（always approve 核心）。"""
    interrupt_on, state = build_permission_interrupts({"execute": "ask"})

    class FakeReq:
        tool_call = {"name": "execute", "args": {"command": "git status"}}

    when = interrupt_on["execute"]["when"]
    assert when(FakeReq()) is True  # ask → 中断

    apply_permission_override(state, "execute", "allow")
    assert when(FakeReq()) is False  # 改 allow 后不再中断


def test_when_predicate_matches_command_pattern():
    """execute 规则集按命令前缀匹配。"""
    interrupt_on, _ = build_permission_interrupts(
        {"execute": {"*": "ask", "git status": "allow"}}
    )

    class FakeReq:
        def __init__(self, cmd):
            self.tool_call = {"name": "execute", "args": {"command": cmd}}

    when = interrupt_on["execute"]["when"]
    assert when(FakeReq("git status")) is False  # allow
    assert when(FakeReq("git commit")) is True  # ask


def test_dump_permissions_roundtrip(tmp_path):
    """dump_permissions_json 把内存配置写回 javis.json。"""
    json_path = tmp_path / "javis.json"
    json_path.write_text(json.dumps({"model": {}, "mcps": []}), encoding="utf-8")

    _, state = build_permission_interrupts({"*": "ask"})
    apply_permission_override(state, "execute", "allow")
    perms = {"*": state["default"]}
    for tool, rule in state["tools"].items():
        if rule != state["default"]:
            perms[tool] = rule
    dump_permissions_json(perms, json_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["permissions"]["execute"] == "allow"
    assert data["model"] == {}


def test_gated_tools_include_execute():
    assert "execute" in GATED_TOOLS
    assert set(GATED_TOOLS) == {"execute", "write_file", "edit_file", "delete"}