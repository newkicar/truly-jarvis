"""SanitizeHistoryMiddleware（400 自愈）回归测试。

Bug：HITL 中断轮 / 流式参数 JSON 截断 → 历史里留下含 invalid_tool_calls 的
AIMessage；下一轮 langchain_openai 把坏参数原样透传给网关 → 400
"Assistant tool call xxx.arguments must be valid JSON"。

Seam: src.sanitize_history.sanitize_messages / SanitizeHistoryMiddleware，
以及 build_agent 整图两轮调用的历史自愈。
"""
import os
import shutil
import tempfile
import time
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from src.agent import build_agent
from src.sanitize_history import SanitizeHistoryMiddleware, sanitize_messages
from tests.conftest import make_fake_config


def _poisoned_history():
    return [
        HumanMessage(content="帮我写个文件", id="h1"),
        AIMessage(
            content="好的，先写 A 再写 B",
            id="a1",
            tool_calls=[{"name": "write_file", "args": {"file_path": "/workspace/a.md"}, "id": "call_ok_1"}],
            invalid_tool_calls=[
                {
                    "type": "invalid_tool_call",
                    "name": "write_file",
                    "args": "{\"file_path\": \"/workspace/b.md",  # 截断的坏 JSON
                    "id": "call_bad_1",
                    "error": "Unterminated string starting at: line 1 column 15",
                }
            ],
        ),
        ToolMessage(content="done a", tool_call_id="call_ok_1", id="t1"),
        ToolMessage(content="synthetic for bad call", tool_call_id="call_bad_1", id="t2"),
    ]


class _PoisonFake(BaseChatModel):
    """第 1 轮吐出带 invalid_tool_calls 的 AIMessage（模拟流截断），
    第 2 轮记录收到的消息并返回干净回复。

    BaseChatModel 是 pydantic 模型，可变状态必须声明为字段（同
    tests/test_agent.py ToolCapableFake 的写法）。"""

    calls: int = 0
    seen_invalid: int | None = None
    seen_orphans: int | None = None

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
                            invalid_tool_calls=[
                                {
                                    "type": "invalid_tool_call",
                                    "name": "write_file",
                                    "args": '{"file_path": "/workspace/bad.md',
                                    "id": "call_bad_42",
                                    "error": "Unterminated string",
                                }
                            ],
                        )
                    )
                ]
            )
        valid_ids = {tc["id"] for m in messages if isinstance(m, AIMessage) for tc in m.tool_calls}
        self.seen_invalid = sum(len(m.invalid_tool_calls) for m in messages if isinstance(m, AIMessage))
        self.seen_orphans = sum(
            1
            for m in messages
            if isinstance(m, ToolMessage) and m.tool_call_id not in valid_ids
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="clean reply"))])

    @property
    def _llm_type(self) -> str:
        return "poison-fake"


def test_sanitize_messages_strips_invalid_calls_and_orphan_tool_messages():
    out = sanitize_messages(_poisoned_history())
    assert out is not None
    assert [m.id for m in out] == ["h1", "a1", "t1"]
    ai = out[1]
    assert isinstance(ai, AIMessage)
    assert ai.invalid_tool_calls == []
    assert [tc["id"] for tc in ai.tool_calls] == ["call_ok_1"]
    assert ai.content == "好的，先写 A 再写 B"
    assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "call_bad_1" for m in out)


def test_sanitize_messages_clean_history_is_noop():
    clean = [
        HumanMessage(content="hi", id="h"),
        AIMessage(content="hello", id="a"),
        ToolMessage(content="x", tool_call_id="c1", id="t"),
    ]
    assert sanitize_messages(clean) is None
    assert sanitize_messages([]) is None


def test_middleware_before_model_update_shape():
    mw = SanitizeHistoryMiddleware()
    update = mw.before_model({"messages": _poisoned_history()}, None)
    assert update is not None
    msgs = update["messages"]
    assert isinstance(msgs[0], RemoveMessage)
    assert msgs[0].id == REMOVE_ALL_MESSAGES
    assert [m.id for m in msgs[1:]] == ["h1", "a1", "t1"]
    assert mw.before_model({"messages": []}, None) is None


def test_poisoned_history_self_heals_on_next_round(monkeypatch):
    """整图两轮：第 1 轮毒化历史，第 2 轮模型输入不得再含 invalid_tool_calls
    与孤儿 ToolMessage（PatchToolCalls 合成结果也要一并清除）。

    不用 pytest 的 tmp_path fixture（本机 pytest 基 temp 目录 teardown
    被 WinError 5 拒绝），改为自建临时目录、尽力清理。"""
    # 不用 tempfile.mkdtemp：受限 token/沙箱环境下它按 0o700 建目录，
    # owner-only ACL 导致目录内无法再建文件（sqlite unable to open database file）；
    # os.makedirs 走继承 ACL，稳定可用。
    base = Path(tempfile.gettempdir()) / f"jarvis_sanitize_{os.getpid()}_{int(time.time() * 1000)}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setenv("JARVIS_HOME", str(base / "jh"))
        cfg = make_fake_config(base)
        model = _PoisonFake()
        with SqliteSaver.from_conn_string(str(base / "cp_poison.db")) as checkpointer:
            agent = build_agent(cfg, model=model, checkpointer=checkpointer)
            tid = "poison-t1"
            agent.invoke(
                {"messages": [HumanMessage(content="round1")]},
                config={"configurable": {"thread_id": tid}},
            )
            out = agent.invoke(
                {"messages": [HumanMessage(content="round2")]},
                config={"configurable": {"thread_id": tid}},
            )
        assert model.calls == 2
        assert model.seen_invalid == 0, "第 2 轮模型输入仍含 invalid_tool_calls"
        assert model.seen_orphans == 0, "第 2 轮模型输入存在引用坏调用的孤儿 ToolMessage"
        assert out["messages"][-1].content == "clean reply"
    finally:
        shutil.rmtree(base, ignore_errors=True)
