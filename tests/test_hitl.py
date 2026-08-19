"""端到端 HITL 审批流程测试。

用 fake 模型触发 execute tool call，验证：
1. interrupt 被触发（stream.interrupted）
2. _handle_interrupts 能收集决策
3. Command(resume) 续跑成功
"""
import warnings

import pytest
from dataclasses import replace

warnings.filterwarnings("ignore")

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from conftest import make_fake_config
from src.agent import build_agent


class ToolCallingFake(BaseChatModel):
    """第一次返回 execute tool call（触发审批），之后返回普通回复。"""

    calls: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "execute",
                                    "args": {"command": "echo hello"},
                                    "id": "call-1",
                                    "type": "tool_call",
                                }
                            ],
                        )
                    )
                ]
            )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="完成"))]
        )

    @property
    def _llm_type(self) -> str:
        return "tool-calling-fake"


from conftest import make_fake_config


def _fake_config(tmp_path):
    return replace(make_fake_config(tmp_path), permissions={"execute": "ask"})


def test_hitl_interrupt_triggers_and_resumes(tmp_path, monkeypatch):
    """执行审批中断 → 批准 → 续跑完成。"""
    import src.main as main

    cfg = _fake_config(tmp_path)
    model = ToolCallingFake()
    agent = build_agent(cfg, model=model)

    # 模拟审批输入：第一次 approve
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    config = {"configurable": {"thread_id": "hitl-test"}, "recursion_limit": 40}
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": "运行命令"}]},
        version="v3",
        config=config,
    )
    for _kind, _item in stream.interleave("messages", "tool_calls", "subagents"):
        pass

    assert stream.interrupted, "应触发审批中断"
    assert stream.interrupts, "应有中断信息"

    # 提取中断，走 CLI 审批处理（模拟输入 y）
    resume = main._handle_interrupts(stream.interrupts, None)
    assert resume is not None
    assert resume["decisions"][0]["type"] == "approve"

    # 用决策续跑
    from langgraph.types import Command

    stream2 = agent.stream_events(
        Command(resume=resume),
        version="v3",
        config=config,
    )
    texts = []
    for kind, item in stream2.interleave("messages", "tool_calls", "subagents"):
        if kind == "messages":
            texts.extend(item.text)
    assert "完成" in "".join(texts) or not stream2.interrupted


def test_hitl_reject_returns_rejection(tmp_path, monkeypatch):
    """拒绝审批 → 决策带 reject 消息。"""
    import src.main as main

    cfg = _fake_config(tmp_path)
    model = ToolCallingFake()
    agent = build_agent(cfg, model=model)
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")

    config = {"configurable": {"thread_id": "hitl-reject"}, "recursion_limit": 40}
    stream = agent.stream_events(
        {"messages": [{"role": "user", "content": "运行命令"}]},
        version="v3",
        config=config,
    )
    for _kind, _item in stream.interleave("messages", "tool_calls", "subagents"):
        pass

    assert stream.interrupted
    resume = main._handle_interrupts(stream.interrupts, None)
    assert resume["decisions"][0]["type"] == "reject"
    assert "拒绝" in resume["decisions"][0]["message"]


def _fake_interrupt(tool="execute", args=None):
    return type(
        "Interrupt",
        (),
        {"value": {"action_requests": [{"name": tool, "args": args or {"command": "ls"}}]}},
    )()


def test_handle_interrupts_edit_returns_edited_action(monkeypatch):
    """CLI e：编辑参数 → resume 带 edited_action。"""
    import src.main as main
    from src import streaming

    interrupts = [_fake_interrupt("execute", {"command": "rm -rf /"})]
    inputs = iter(["e", "echo safe"])
    real_cli = streaming.cli_prompt_action

    def inject_input_cli(inv, **kwargs):
        return real_cli(
            inv,
            permission_state=kwargs.get("permission_state"),
            input_fn=lambda _: next(inputs),
        )

    monkeypatch.setattr(streaming, "cli_prompt_action", inject_input_cli)
    resume = main._handle_interrupts(interrupts, {"default": "ask", "tools": {}})
    assert resume is not None
    decision = resume["decisions"][0]
    assert decision["type"] == "edit"
    assert decision["edited_action"]["name"] == "execute"
    assert decision["edited_action"]["args"]["command"] == "echo safe"


def test_handle_interrupts_always_approve_updates_state_and_json(monkeypatch, tmp_path):
    """CLI a：always approve → permission_state 更新并写 javis.json。"""
    import src.main as main
    from src import streaming

    interrupts = [_fake_interrupt("execute", {"command": "git status"})]
    state = {"default": "ask", "tools": {"execute": "ask", "write_file": "ask"}}
    written = {}

    import src.commands as cmds
    import src.permissions as perms

    def fake_dump(permissions, json_path):
        written["permissions"] = permissions
        written["path"] = json_path

    def fake_apply(st, tool, action, value="*"):
        st["tools"][tool] = action

    monkeypatch.setattr(cmds, "project_root", lambda: tmp_path)
    monkeypatch.setattr(perms, "dump_permissions_json", fake_dump)
    monkeypatch.setattr(perms, "apply_permission_override", fake_apply)

    real_cli = streaming.cli_prompt_action

    def inject_input_cli(inv, **kwargs):
        return real_cli(
            inv,
            permission_state=kwargs.get("permission_state"),
            input_fn=lambda _: "a",
            on_always_approve=kwargs.get("on_always_approve"),
        )

    monkeypatch.setattr(streaming, "cli_prompt_action", inject_input_cli)
    resume = main._handle_interrupts(interrupts, state)
    assert resume is not None
    assert resume["decisions"][0]["type"] == "approve"
    assert state["tools"]["execute"] == "allow"
    assert written["permissions"] == {"execute": "allow"}
    assert written["path"] == tmp_path / "javis.json"