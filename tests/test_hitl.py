"""端到端 HITL 审批流程测试。

用 fake 模型触发 execute tool call，验证：
1. interrupt 被触发（stream.interrupted）
2. _handle_interrupts 能收集决策
3. Command(resume) 续跑成功
"""
import warnings

import pytest

warnings.filterwarnings("ignore")

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agent import build_agent
from src.config import Config


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


def _fake_config(tmp_path) -> Config:
    return Config(
        base_url="https://fake/v1",
        api_key="sk",
        model_id="m",
        tavily_key="tvly",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(),
        mcps=(),
        permissions={"execute": "ask"},
    )


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