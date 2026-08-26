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
    json_path = tmp_path / "jarvis.json"
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


def _fake_req(tool: str, args: dict, tid: str = "t1"):
    """构造最小 ToolCallRequest（仅暴露 tool_call，middleware 只读该字段）。"""
    from typing import cast

    from langchain.agents.middleware.types import ToolCallRequest
    from types import SimpleNamespace

    return cast(
        ToolCallRequest,
        SimpleNamespace(tool_call={"name": tool, "args": args, "id": tid}),
    )


def test_deny_middleware_blocks_execute():
    """deny 规则下 execute 工具调用被拦截，不执行 handler。"""
    from langchain_core.messages import ToolMessage

    from src.permissions import (
        PermissionDenyMiddleware,
        build_permission_deny_middleware,
        build_permission_interrupts,
    )

    interrupt_on, state = build_permission_interrupts(
        {"execute": {"*": "allow", "rm *": "deny"}}
    )

    req = _fake_req("execute", {"command": "rm -rf /tmp/x"})

    # deny 不中断：when 谓词返回 False（拦截走工具层，不弹审批）
    assert interrupt_on["execute"]["when"](req) is False

    mw = build_permission_deny_middleware(state)
    assert isinstance(mw, PermissionDenyMiddleware)

    called = []

    def handler(_req):
        called.append(True)
        return ToolMessage(content="ok", name="execute", tool_call_id="t1")

    out = mw.wrap_tool_call(req, handler)
    assert called == []  # 未执行工具
    assert isinstance(out, ToolMessage)
    assert out.status == "error"
    assert "deny" in out.content


def test_deny_middleware_passes_allow_through():
    """非 deny 调用放行，正常执行 handler。"""
    from langchain_core.messages import ToolMessage

    from src.permissions import build_permission_deny_middleware, build_permission_interrupts

    _interrupt_on, state = build_permission_interrupts(
        {"execute": {"*": "allow", "rm *": "deny"}}
    )
    mw = build_permission_deny_middleware(state)

    req = _fake_req("execute", {"command": "git status"}, "t2")

    called = []

    def handler(_req):
        called.append(True)
        return ToolMessage(content="ok", name="execute", tool_call_id="t2")

    out = mw.wrap_tool_call(req, handler)
    assert called == [True]
    assert isinstance(out, ToolMessage) and out.content == "ok"


def test_deny_middleware_respects_override():
    """运行时改 state 为 allow，deny 立即失效（共享引用）。"""
    from langchain_core.messages import ToolMessage

    from src.permissions import (
        apply_permission_override,
        build_permission_deny_middleware,
        build_permission_interrupts,
    )

    _interrupt_on, state = build_permission_interrupts({"execute": "deny"})
    mw = build_permission_deny_middleware(state)

    req = _fake_req("execute", {"command": "anything"}, "t3")

    def handler(_req):
        return ToolMessage(content="ok", name="execute", tool_call_id="t3")

    out1 = mw.wrap_tool_call(req, handler)
    assert isinstance(out1, ToolMessage) and out1.status == "error"

    apply_permission_override(state, "execute", "allow")
    out2 = mw.wrap_tool_call(req, handler)
    assert isinstance(out2, ToolMessage) and out2.content == "ok"


def test_deny_middleware_async_blocks(monkeypatch):
    """awrap_tool_call（stream_events 路径）同样拦截 deny。"""
    import asyncio

    from langchain_core.messages import ToolMessage

    from src.permissions import build_permission_deny_middleware, build_permission_interrupts

    _interrupt_on, state = build_permission_interrupts({"write_file": "deny"})
    mw = build_permission_deny_middleware(state)

    req = _fake_req(
        "write_file",
        {"file_path": "/vault/Inbox/危险.md", "content": "x"},
        "t4",
    )

    async def handler(_req):
        return ToolMessage(content="ok", name="write_file", tool_call_id="t4")

    out = asyncio.run(mw.awrap_tool_call(req, handler))
    assert isinstance(out, ToolMessage)
    assert out.status == "error"
    assert "deny" in out.content