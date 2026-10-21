"""审批权限模块测试（src.permissions）。

Seam: build_permission_interrupts / resolve_tool_action / apply_permission_override
/ dump_permissions_json。验证配置→interrupt_on 映射、规则集匹配、always approve
的运行时可变引用 + 持久化。
"""
import json

from src.permissions import (
    GATED_TOOLS,
    _action_for_args,
    apply_permission_override,
    build_permission_interrupts,
    build_permission_interrupts_from_state,
    dump_permissions_json,
    resolve_tool_action,
    yolo_active,
    yolo_off,
    yolo_on,
)


def test_default_all_ask():
    """不配置 permissions 时，所有 gated tool 默认 ask（每次审批）。"""
    interrupt_on, state = build_permission_interrupts({})
    assert "execute" in interrupt_on
    assert "write_file" in interrupt_on
    assert "edit_file" in interrupt_on
    assert "delete" in interrupt_on
    assert state["default"] == "ask"
    assert interrupt_on["execute"]["allowed_decisions"] == ["approve", "reject", "edit"]
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


def test_edit_decision_allowed_for_all_gated_tools():
    """所有 gated 工具开放 "edit" 决策（UI/CLI 对所有工具提供编辑参数入口）。"""
    interrupt_on, _ = build_permission_interrupts({})
    for tool in GATED_TOOLS:
        assert "edit" in interrupt_on[tool]["allowed_decisions"], tool


def test_langchain_hitl_edit_decision_rewrites_tool_calls(monkeypatch):
    """行为回归：execute/delete 收到 "edit" 决策后，编辑后参数在工具执行层生效。

    此前 execute/delete 的 allowed_decisions 缺 "edit"，langchain 的
    _process_decision 抛 ValueError，编辑后的参数到不了工具执行层
    （审批弹窗里改完参数确认后整轮报错、被放弃）。

    存储形式随 langchain 版本变化：1.3.x 在 AIMessage.tool_calls 原地改写；
    1.4.x 原调用留在消息里，改写存入 "hitl_edited_tool_calls"
    （tool_call id -> {"name","args"}），由 wrap_tool_call 执行期替换。
    断言对两种存储形式都接受（版本无关）。
    """
    from types import SimpleNamespace

    import langchain.agents.middleware.human_in_the_loop as hitl_mod
    from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
    from langchain_core.messages import AIMessage

    interrupt_on, _state = build_permission_interrupts({})
    mw = HumanInTheLoopMiddleware(interrupt_on=interrupt_on)

    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "execute",
                "args": {"command": "python -c 'print(old)'"},
                "id": "c1",
                "type": "tool_call",
            },
            {
                "name": "delete",
                "args": {"file_path": "approval-test.txt"},
                "id": "c2",
                "type": "tool_call",
            },
        ],
    )
    state = {"messages": [ai]}
    runtime = SimpleNamespace(
        context=None,
        stream_writer=None,
        store=None,
        execution_info=None,
        server_info=None,
    )

    monkeypatch.setattr(
        hitl_mod,
        "interrupt",
        lambda req: {
            "decisions": [
                {
                    "type": "edit",
                    "edited_action": {
                        "name": "execute",
                        "args": {"command": "python -c 'print(new)'"},
                    },
                },
                {
                    "type": "edit",
                    "edited_action": {
                        "name": "delete",
                        "args": {"file_path": "approval-test2.txt"},
                    },
                },
            ]
        },
    )

    result = mw.after_model(state, runtime)

    edited: dict = {}
    for holder in (state, result if isinstance(result, dict) else {}):
        holder_edited = holder.get("hitl_edited_tool_calls")
        if isinstance(holder_edited, dict):
            edited.update(holder_edited)
    assert ai.tool_calls[0]["args"]["command"] == "python -c 'print(new)'" or \
        edited.get("c1", {}).get("args", {}).get("command") == "python -c 'print(new)'"
    assert ai.tool_calls[1]["args"]["file_path"] == "approval-test2.txt" or \
        edited.get("c2", {}).get("args", {}).get("file_path") == "approval-test2.txt"


def test_hitl_reject_decision_on_delete_still_works(monkeypatch):
    """delete 的 "reject" 决策仍返回拒绝 ToolMessage（开放 edit 不影响 reject）。"""
    from types import SimpleNamespace

    import langchain.agents.middleware.human_in_the_loop as hitl_mod
    from langchain.agents.middleware.human_in_the_loop import HumanInTheLoopMiddleware
    from langchain_core.messages import AIMessage, ToolMessage

    interrupt_on, _state = build_permission_interrupts({})
    mw = HumanInTheLoopMiddleware(interrupt_on=interrupt_on)

    ai = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "delete",
                "args": {"file_path": "x.txt"},
                "id": "c9",
                "type": "tool_call",
            },
        ],
    )
    state = {"messages": [ai]}
    runtime = SimpleNamespace(
        context=None,
        stream_writer=None,
        store=None,
        execution_info=None,
        server_info=None,
    )
    monkeypatch.setattr(
        hitl_mod,
        "interrupt",
        lambda req: {"decisions": [{"type": "reject", "message": "用户拒绝"}]},
    )

    out = mw.after_model(state, runtime)
    assert out is not None
    tool_msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c9"
    assert "拒绝" in tool_msgs[0].content


# ---------------------------------------------------------------------------
# YOLO 模式（tui-ux12）：线程级免审批，_action_for_args 顶部短路
# ---------------------------------------------------------------------------

def test_yolo_state_initialised_with_yolo_threads():
    """build_permission_interrupts 返回的 state 含 yolo_threads: set()。"""
    _io, state = build_permission_interrupts({})
    assert state["yolo_threads"] == set()


def test_build_permission_interrupts_from_state_ensures_yolo_key():
    """复用路径：缺键时 setdefault 保证 yolo_threads 存在。"""
    _io, state = build_permission_interrupts({})
    del state["yolo_threads"]
    build_permission_interrupts_from_state(state)
    assert state["yolo_threads"] == set()


def test_yolo_active_pure_functions():
    """yolo_on/off/active 纯函数组：空 id / 缺键 state / 成员 / 非成员。"""
    state = {"thread_id": "t"}
    assert yolo_active(state, "") is False  # 空串 id
    assert yolo_active(state, "t") is False  # state 缺 yolo_threads 键（旧引用防御）
    state["yolo_threads"] = set()
    assert yolo_active(state, "t") is False  # 非成员
    assert yolo_on(state, "t") is True
    assert yolo_active(state, "t") is True  # 成员
    assert yolo_on(state, "t") is True  # 幂等 on
    assert yolo_on(state, "") is False  # 空 id no-op
    yolo_off(state, "t")
    assert yolo_active(state, "t") is False
    yolo_off(state, "t")  # 幂等 off，不报错
    yolo_off(state, "")


def test_yolo_on_allows_all_gated_tools_including_deny():
    """yolo 下 4 个 gated 工具全 allow（含原本 deny 的 bypass）；when 与 deny 双路绕过。"""
    from langchain_core.messages import ToolMessage

    from src.permissions import build_permission_deny_middleware

    io, state = build_permission_interrupts(
        {"execute": "ask", "write_file": "deny", "edit_file": "ask", "delete": "ask"}
    )
    state["thread_id"] = "t-yolo"
    yolo_on(state, "t-yolo")

    args = {
        "execute": {"command": "rm -rf /"},
        "write_file": {"file_path": "x.md", "content": "x"},
        "edit_file": {"file_path": "x.md", "old_string": "a", "new_string": "b"},
        "delete": {"file_path": "x.md"},
    }
    for tool, a in args.items():
        assert _action_for_args(state, tool, a) == "allow", tool

    # ask 路：dict 形态的 when 谓词不再中断
    for tool in GATED_TOOLS:
        entry = io[tool]
        if isinstance(entry, dict):
            assert entry["when"](_fake_req(tool, args[tool])) is False, tool

    # deny 路：原本 deny 的 write_file 拦截 middleware 不再 block
    mw = build_permission_deny_middleware(state)
    req = _fake_req("write_file", args["write_file"])
    called = []

    def handler(_req):
        called.append(True)
        return ToolMessage(content="ok", name="write_file", tool_call_id="w1")

    out = mw.wrap_tool_call(req, handler)
    assert called == [True]
    assert isinstance(out, ToolMessage) and out.content == "ok"


def test_yolo_off_restores_original_rules():
    """off 后 deny 回 deny、ask 回 ask；state["tools"]/default 前后零 diff。"""
    io, state = build_permission_interrupts(
        {"execute": "ask", "write_file": "deny", "edit_file": "ask", "delete": "ask"}
    )
    state["thread_id"] = "t1"
    tools_snapshot = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in state["tools"].items()
    }
    default_snapshot = state["default"]

    yolo_on(state, "t1")
    assert _action_for_args(state, "execute", {"command": "x"}) == "allow"
    assert _action_for_args(state, "write_file", {"file_path": "x"}) == "allow"

    yolo_off(state, "t1")
    assert _action_for_args(state, "execute", {"command": "x"}) == "ask"
    assert _action_for_args(state, "write_file", {"file_path": "x"}) == "deny"
    assert _action_for_args(state, "edit_file", {"file_path": "x"}) == "ask"
    assert _action_for_args(state, "delete", {"file_path": "x"}) == "ask"

    # 规则原样（jarvis.json / state["tools"] 零 diff）
    assert state["tools"] == tools_snapshot
    assert state["default"] == default_snapshot
    assert state["yolo_threads"] == set()


def test_yolo_thread_isolation():
    """线程 A yolo、线程 B 仍按原规则（线程级隔离）。"""
    io, state = build_permission_interrupts({"execute": "ask"})
    yolo_on(state, "a")
    state["thread_id"] = "b"
    assert yolo_active(state, "a") and not yolo_active(state, "b")
    assert _action_for_args(state, "execute", {"command": "x"}) == "ask"
    assert io["execute"]["when"](_fake_req("execute", {"command": "x"}, "b")) is True
    state["thread_id"] = "a"
    assert _action_for_args(state, "execute", {"command": "x"}) == "allow"


def test_yolo_bypasses_hook_decisions(monkeypatch):
    """yolo 短路置于 hooks 之前：hook deny 被 bypass；off 后 hook 恢复生效。"""
    from src import permission_hooks

    io, state = build_permission_interrupts(
        {"execute": "allow"},
        hooks={"permission": [{"match": "execute", "command": ["echo", "x"]}]},
    )
    state["thread_id"] = "ta"
    assert state["hooks"], "hook 规则应已解析入 state"

    calls = []

    def fake_resolve(rules, tool, args, *, thread_id="", project_root=None):
        calls.append(tool)
        return "deny", "hook says deny"

    monkeypatch.setattr(permission_hooks, "resolve_permission_hook", fake_resolve)

    # 无 yolo → hook deny 生效（execute 的 allow 被 hook 覆盖）
    assert _action_for_args(state, "execute", {"command": "any"}) == "deny"

    yolo_on(state, "ta")
    assert _action_for_args(state, "execute", {"command": "any"}) == "allow"
    assert len(calls) == 1, "yolo 短路不应再进入 hook 判定"

    yolo_off(state, "ta")
    assert _action_for_args(state, "execute", {"command": "any"}) == "deny"
