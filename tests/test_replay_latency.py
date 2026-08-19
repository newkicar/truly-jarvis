"""Phase-1 loop: /replay of a completed 「你好」 input checkpoint must be instant.

User symptom: /history 里这条只是「你好」，重跑却要等很久才显示。
Cause to catch: replay re-executes the model instead of showing the saved turn.
"""
from __future__ import annotations

import time

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from src import commands, streaming
from src.agent import build_agent
from conftest import make_fake_config


class CountingFake(BaseChatModel):
    reply: str = "你好！我是 JARVIS。"
    generate_calls: int = 0
    delay_s: float = 0.0

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.generate_calls += 1
        if self.delay_s:
            time.sleep(self.delay_s)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self.reply))]
        )

    @property
    def _llm_type(self) -> str:
        return "counting-fake"


def _completed_hello_agent(tmp_path, delay_s: float = 0.0):
    cfg = make_fake_config(tmp_path)
    model = CountingFake(reply="你好！我是 JARVIS。", delay_s=delay_s)
    saver = InMemorySaver()
    agent = build_agent(cfg, model=model, checkpointer=saver)
    agent.invoke(
        {"messages": [HumanMessage(content="你好")]},
        config={"configurable": {"thread_id": "hello"}, "recursion_limit": 30},
    )
    bounds = commands.boundary_checkpoints(agent, "hello")
    assert bounds, "expected an input checkpoint after 你好"
    input_cid = bounds[0].config["configurable"]["checkpoint_id"]
    return agent, model, input_cid


def test_replay_completed_hello_is_faster_than_model_call(tmp_path):
    """重跑已完成的「你好」不得再等一轮模型延迟。"""
    delay = 0.8
    agent, model, input_cid = _completed_hello_agent(tmp_path, delay_s=delay)
    calls_after_turn = model.generate_calls
    assert calls_after_turn >= 1

    started = time.perf_counter()
    streaming.run_agent_turn(
        agent,
        "hello",
        None,
        checkpoint_id=input_cid,
        handle_interrupts=lambda _: None,
        callbacks={
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: None,
        },
    )
    elapsed = time.perf_counter() - started

    assert model.generate_calls == calls_after_turn, (
        f"replay re-called the model ({calls_after_turn} -> {model.generate_calls}); "
        "completed hello should display the saved turn"
    )
    assert elapsed < delay / 2, (
        f"replay of completed 你好 took {elapsed:.2f}s (model delay={delay}s)"
    )
