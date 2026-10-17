"""commands.undo（消息层撤回）单测：head 外科删除语义——撤 1 / 反复撤至空白 / 撤超出 / 无消息。

实现定稿（tui-ux6 #01）：undo 基于 live head 状态的外科式删除（RemoveMessage +
as_node="model"），不依赖 get_state_history 的 append-only 日志；反复调用每次再
撤一轮，撤到空白后继续调用返回「没有可撤回的消息」而非异常。
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite import SqliteSaver

from src import commands
from src.agent import build_agent
from tests.conftest import make_fake_config


class _Head:
    def __init__(self, messages):
        self.values = {"messages": messages}


class _UndoAgent:
    """fake agent：head 上三轮对话（m1..m6 交替 Human/AI）。"""

    def __init__(self):
        m1, a1 = HumanMessage("问题 1", id="m1"), AIMessage("回答 1", id="m2")
        m2, a2 = HumanMessage("问题 2", id="m3"), AIMessage("回答 2", id="m4")
        m3, a3 = HumanMessage("问题 3", id="m5"), AIMessage("回答 3", id="m6")
        self._head_msgs = [m1, a1, m2, a2, m3, a3]
        self.updates = []

    def get_state(self, config):
        assert config == commands.thread_config("t1")
        return _Head(self._head_msgs)

    def update_state(self, config, values=None, as_node=None):
        self.updates.append((config, values, as_node))
        doomed = {rm.id for rm in values["messages"] if isinstance(rm, RemoveMessage)}
        self._head_msgs = [
            m for m in self._head_msgs if getattr(m, "id", None) not in doomed
        ]


class _BlankAgent:
    def get_state(self, config):
        return _Head([])

    def update_state(self, config, values=None, as_node=None):
        raise AssertionError("空白会话不应 update_state")


def test_undo_one_removes_last_turn():
    agent = _UndoAgent()
    text = commands.undo(agent, "t1", 1)
    assert "已撤回 1 条消息" in text
    assert len(agent.updates) == 1
    cfg, values, as_node = agent.updates[0]
    assert cfg == commands.thread_config("t1")
    assert as_node == "model"  # 外科式删除（fork 先例）
    assert {rm.id for rm in values["messages"]} == {"m5", "m6"}
    assert [m.id for m in agent._head_msgs] == ["m1", "m2", "m3", "m4"]


def test_undo_repeated_loops_to_blank_then_notices():
    """关键稳定性诉求：反复调用每次再撤一轮，撤到空白后返回提示而非异常。"""
    agent = _UndoAgent()
    for _ in range(3):
        assert "已撤回 1 条消息" in commands.undo(agent, "t1", 1)
    assert agent._head_msgs == []
    assert "没有可撤回的消息" in commands.undo(agent, "t1", 1)
    assert len(agent.updates) == 3  # 空白后不再产生 update


def test_undo_exceeds_clamps_with_notice():
    agent = _UndoAgent()
    text = commands.undo(agent, "t1", 99)
    assert "已撤回 3 条消息" in text
    assert "已超出" in text
    assert len(agent.updates) == 1  # 一次外科删除撤到空白
    assert agent._head_msgs == []


def test_undo_blank_returns_notice_without_update():
    agent = _BlankAgent()
    assert "没有可撤回的消息" in commands.undo(agent, "t1", 1)


class _TextFake(BaseChatModel):
    """三轮对话用的最简 fake（build_agent 要求 bind_tools 存在）。"""

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(
            generations=[
                ChatGeneration(message=AIMessage(content=f"回答 {len(messages)}"))
            ]
        )

    @property
    def _llm_type(self) -> str:
        return "undo-e2e-fake"


def test_undo_loop_to_blank_on_real_graph():
    """回归（tui-ux6 #01 定稿）：真图三轮对话 → 循环 undo 至空白 → 空白后再 undo
    返回「没有可撤回的消息」而非异常。

    不用 pytest 的 tmp_path fixture（本机 pytest 基 temp 目录 teardown
    被 WinError 5 拒绝），改为自建临时目录、尽力清理。"""
    base = Path(tempfile.gettempdir()) / f"jarvis_undo_e2e_{os.getpid()}_{int(time.time() * 1000)}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.environ["JARVIS_HOME"] = str(base / "jh")
        cfg = make_fake_config(base)
        model = _TextFake()
        with SqliteSaver.from_conn_string(str(base / "undo_e2e.db")) as saver:
            agent = build_agent(cfg, model=model, checkpointer=saver)
            tid = "undo-e2e"
            for i in range(3):
                agent.invoke(
                    {"messages": [HumanMessage(content=f"问题 {i + 1}")]},
                    config={"configurable": {"thread_id": tid}},
                )
            assert (agent.get_state(commands.thread_config(tid)).values or {}).get(
                "messages"
            )
            for _ in range(3):
                assert "已撤回 1 条消息" in commands.undo(agent, tid, 1)
            head = agent.get_state(commands.thread_config(tid))
            assert (head.values or {}).get("messages") in ([], None)
            assert "没有可撤回的消息" in commands.undo(agent, tid, 1)
    finally:
        shutil.rmtree(base, ignore_errors=True)
