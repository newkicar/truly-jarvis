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
        AIMessage(
            content="hello",
            id="a",
            tool_calls=[{"name": "ls", "args": {}, "id": "c1", "type": "tool_call"}],
        ),
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


def test_sanitize_messages_strips_empty_tool_call_and_orphan_result():
    """真实 checkpoint 复现的脏对（400 'missing field tool_call_id' 触发源）：
    - AIMessage.tool_calls 里混入 name="" + id="" 的空工具调用（合法列表，
      不在 invalid_tool_calls 里，旧实现完全漏掉）；
    - ToolNode 对空名调用产生的 error ToolMessage，tool_call_id=""（孤儿）。
    两者必须成对清除，合法调用及其结果原样保留。"""
    ai_dirty = AIMessage(
        content="",
        id="a16",
        tool_calls=[
            {"name": "", "args": {"query": "x"}, "id": "", "type": "tool_call"},
            {"name": "task", "args": {}, "id": "call_b4dee9d", "type": "tool_call"},
        ],
    )
    tm_ok = ToolMessage(
        content="ok result", tool_call_id="call_b4dee9d", id="t17", status="success"
    )
    tm_orphan = ToolMessage(
        content="Error:  is not a valid tool, try one of [ls]",
        tool_call_id="",
        id="t18",
        status="error",
    )
    out = sanitize_messages([HumanMessage(content="q", id="h"), ai_dirty, tm_ok, tm_orphan])
    assert out is not None
    assert [m.id for m in out] == ["h", "a16", "t17"]
    ai = out[1]
    assert isinstance(ai, AIMessage)
    assert [(tc["name"], tc["id"]) for tc in ai.tool_calls] == [("task", "call_b4dee9d")]
    assert ai.invalid_tool_calls == []
    assert not any(isinstance(m, ToolMessage) and not m.tool_call_id for m in out)


def test_sanitize_messages_strips_none_tool_call_id():
    """tool_call_id=None 的孤儿 ToolMessage（model_construct 可绕过校验产出）
    也要清除；id 非空但 name 为空的调用同样算脏（网关序列化后 name="" 拒收）。"""
    ai = AIMessage(
        content="",
        id="a",
        tool_calls=[
            {"name": "", "args": {}, "id": "call_noname", "type": "tool_call"},
            {"name": "ls", "args": {}, "id": "call_ls", "type": "tool_call"},
        ],
    )
    tm_noname = ToolMessage(content="err", tool_call_id="call_noname", id="t1", status="error")
    tm_ls = ToolMessage(content="dir listing", tool_call_id="call_ls", id="t2")
    tm_none = ToolMessage.model_construct(content="x", tool_call_id=None, id="t3")
    out = sanitize_messages([ai, tm_noname, tm_ls, tm_none])
    assert out is not None
    assert [m.id for m in out] == ["a", "t2"]
    assert [(tc["name"], tc["id"]) for tc in out[0].tool_calls] == [("ls", "call_ls")]


class _EmptyCallPoisonFake(BaseChatModel):
    """第 1 轮吐出「空 name+id 调用 + 合法 ls 调用」（真实事故形态：流式聚合
    产出脏 tool_call），ToolNode 会把空名调用执行成 error 结果并写回
    tool_call_id="" 的 ToolMessage——即 checkpoint 里的脏对；
    第 2 轮记录模型输入，断言脏数据已被清洗。"""

    calls: int = 0
    seen_empty_calls: int | None = None
    seen_empty_tcid: int | None = None

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
                                {"name": "", "args": {"query": "x"}, "id": "", "type": "tool_call"},
                                {"name": "ls", "args": {}, "id": "call_ls_1", "type": "tool_call"},
                            ],
                        )
                    )
                ]
            )
        self.seen_empty_calls = sum(
            1
            for m in messages
            if isinstance(m, AIMessage)
            for tc in m.tool_calls
            if not tc.get("name") or not tc.get("id")
        )
        self.seen_empty_tcid = sum(
            1 for m in messages if isinstance(m, ToolMessage) and not m.tool_call_id
        )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="clean reply"))])

    @property
    def _llm_type(self) -> str:
        return "empty-call-poison-fake"


def test_empty_call_history_self_heals_on_next_round(monkeypatch):
    """整图两轮复现真实事故：第 1 轮模型产出空 name/id 的 tool_call，
    ToolNode 执行出 error 结果（tci=""）写进 checkpoint；第 2 轮模型输入
    不得再含空调用与空 tci 结果，否则网关 400 'missing field tool_call_id'。

    同前：不用 pytest tmp_path / mkdtemp（WinError 5 中毒），自建目录。"""
    base = Path(tempfile.gettempdir()) / f"jarvis_emptycall_{os.getpid()}_{int(time.time() * 1000)}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        monkeypatch.setenv("JARVIS_HOME", str(base / "jh"))
        cfg = make_fake_config(base)
        model = _EmptyCallPoisonFake()
        with SqliteSaver.from_conn_string(str(base / "cp_empty.db")) as checkpointer:
            agent = build_agent(cfg, model=model, checkpointer=checkpointer)
            tid = "empty-t1"
            agent.invoke(
                {"messages": [HumanMessage(content="round1")]},
                config={"configurable": {"thread_id": tid}},
            )
            out = agent.invoke(
                {"messages": [HumanMessage(content="round2")]},
                config={"configurable": {"thread_id": tid}},
            )
        # round1 内含工具循环（空调用 + 合法 ls 调用都触发 ToolNode 回环）→ 模型调用 2 次；
        # round2 再调用 1 次；故共 3 次（非 2）。
        assert model.calls == 3
        assert model.seen_empty_calls == 0, "第 2 轮模型输入仍含空 name/id 的 tool_call"
        assert model.seen_empty_tcid == 0, "第 2 轮模型输入仍含空 tool_call_id 的孤儿结果"
        assert out["messages"][-1].content == "clean reply"

        # 脏对已在 checkpoint 里持久清除（第 2 轮 before_model 整表重写落库）
        with SqliteSaver.from_conn_string(str(base / "cp_empty.db")) as saver2:
            agent2 = build_agent(cfg, model=_EmptyCallPoisonFake(), checkpointer=saver2)
            live = agent2.get_state({"configurable": {"thread_id": tid}}).values["messages"]
            assert not any(
                isinstance(m, AIMessage)
                and any(not tc.get("name") or not tc.get("id") for tc in m.tool_calls)
                for m in live
            ), "checkpoint 里仍残留空 tool_call"
            assert not any(isinstance(m, ToolMessage) and not m.tool_call_id for m in live), (
                "checkpoint 里仍残留空 tool_call_id 结果"
            )
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_sanitize_messages_drops_non_string_tool_call_id():
    """"Expected 'id' to be a string."（网关 Rust serde 严格类型）触发源：
    ``.tool_calls`` 里 id 为 int（真值非空，旧的 truthiness 检查放过）→ 整条
    调用丢弃，对应 ToolMessage 一并清除（否则制造孤儿）。"""
    # pydantic 正常构造会拒收 int id；用 model_construct 模拟旧 checkpoint
    # 反序列化 / 第三方中间件塞入的脏数据。
    ai = AIMessage.model_construct(
        content="",
        id="a_int",
        tool_calls=[
            {"name": "ls", "args": {}, "id": 42, "type": "tool_call"},
            {"name": "read_file", "args": {"path": "x"}, "id": "call_ok", "type": "tool_call"},
        ],
        invalid_tool_calls=[],
        additional_kwargs={},
        response_metadata={},
    )
    tm_int = ToolMessage.model_construct(content="dir", tool_call_id=42, id="t_int")
    tm_ok = ToolMessage(content="content", tool_call_id="call_ok", id="t_ok")
    out = sanitize_messages([ai, tm_int, tm_ok])
    assert out is not None
    assert [m.id for m in out] == ["a_int", "t_ok"]
    assert [(tc["name"], tc["id"]) for tc in out[0].tool_calls] == [("read_file", "call_ok")]


def test_sanitize_messages_drops_dirty_raw_tool_calls_in_additional_kwargs():
    """流式中断残留的 ``additional_kwargs["tool_calls"]``（id=None）在
    ``.tool_calls`` 为空时被 langchain_openai 原样透传给网关 → 400
    "Expected 'id' to be a string."；必须连原始列表一起清掉。"""
    ai = AIMessage(
        content="",
        id="a_raw",
        additional_kwargs={
            "tool_calls": [
                {"id": None, "type": "function", "function": {"name": "execute", "arguments": "{}"}}
            ]
        },
    )
    out = sanitize_messages([HumanMessage(content="q", id="h"), ai])
    assert out is not None
    fixed = out[1]
    assert isinstance(fixed, AIMessage)
    assert "tool_calls" not in fixed.additional_kwargs
    assert fixed.tool_calls == []


def test_sanitize_messages_keeps_valid_raw_tool_calls_untouched():
    """全合法的原始 tool_calls（字符串 id + 字符串 name）不算脏：零改动返回 None。"""
    ai = AIMessage(
        content="",
        id="a_ok",
        additional_kwargs={
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "ls", "arguments": "{}"}}
            ]
        },
    )
    assert sanitize_messages([HumanMessage(content="q", id="h"), ai]) is None
