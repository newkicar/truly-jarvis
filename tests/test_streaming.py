"""streaming 消费层测试。"""
import threading
import time

import pytest

from src import streaming


class _Msg:
    def __init__(self, text: str):
        self.text = list(text)


class _Tool:
    def __init__(self, name, input="", output=None, error=None):
        self.tool_name = name
        self.input = input
        self.output = output
        self.error = error


class _Sub:
    def __init__(self, name, status, tool_calls=None):
        self.name = name
        self.status = status
        self.tool_calls = tool_calls or []


class _Stream:
    def __init__(self, items):
        self._items = items
        self.interrupted = False
        self.interrupts = None
        self.output = None

    def interleave(self, *kinds):
        yield from self._items


def test_consume_stream_tool_output_and_subagent_nesting():
    stream = _Stream(
        [
            ("subagents", _Sub("researcher", "started", [_Tool("grep", "x", output="hit1\nhit2")])),
            ("tool_calls", _Tool("read_file", "/vault/a.md", output="content line")),
            ("messages", _Msg("答案")),
        ]
    )
    tools = []
    segments = []

    streaming.consume_stream_events(
        stream,
        {
            "on_subagent": lambda n, s, d: tools.append(("sub", n, s, d)),
            "on_tool_call": lambda n, a, e, o, d: tools.append(("tool", n, o, d)),
            "on_message_delta": lambda d: None,
            "on_message_end": lambda seg: segments.append(seg),
        },
    )

    assert any(t[0] == "sub" and t[1] == "researcher" for t in tools)
    nested = [t for t in tools if t[0] == "tool" and t[1] == "grep"]
    assert nested and "hit1" in nested[0][2]
    top = [t for t in tools if t[0] == "tool" and t[1] == "read_file"]
    assert top and top[0][3] >= 1
    assert segments == ["答案"]


def test_consume_stream_skips_tool_call_message_blocks():
    tool_block = {
        "type": "tool_call",
        "id": "call_1",
        "name": "task",
        "args": {"subagent_type": "researcher"},
    }

    class _Msg:
        def __init__(self, text):
            self.text = text

    stream = _Stream([("messages", _Msg([tool_block])), ("tool_calls", _Tool("task", "researcher"))])
    segments = []
    deltas = []

    streaming.consume_stream_events(
        stream,
        {
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: deltas.append(d),
            "on_message_end": lambda seg: segments.append(seg),
        },
    )

    assert deltas == []
    assert segments == []


def test_run_agent_turn_replay_uses_checkpoint_config():
    class _Stream:
        def __init__(self):
            self.interrupted = False
            self.interrupts = None
            self.output = None

        def interleave(self, *kinds):
            if False:
                yield

    class FakeAgent:
        def __init__(self):
            self.calls = []

        def stream_events(self, payload, *, version, config, control=None):
            self.calls.append((payload, version, config))
            return _Stream()

    agent = FakeAgent()
    streaming.run_agent_turn(
        agent,
        "t",
        None,
        checkpoint_id="cid-0000000-aaaa",
        handle_interrupts=lambda _: None,
        callbacks={
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: None,
        },
    )
    assert len(agent.calls) == 1
    payload, version, config = agent.calls[0]
    assert payload is None
    assert version == "v3"
    assert config["configurable"] == {"thread_id": "t", "checkpoint_ns": "", "checkpoint_id": "cid-0000000-aaaa"}


def test_run_agent_turn_replay_emits_saved_turn_without_stream():
    class FakeState:
        def __init__(self):
            self.config = {"configurable": {"checkpoint_id": "cid-input"}}
            self.metadata = {"source": "input"}
            self.values = {"messages": [type("A", (), {"type": "ai", "content": "saved-hello"})()]}
            self.next = ()

    class FakeAgent:
        def __init__(self):
            self.stream_calls = []

        def get_state_history(self, config=None):
            return iter([FakeState()])

        def stream_events(self, payload, *, version, config, control=None):
            self.stream_calls.append((payload, version, config))
            raise AssertionError("completed replay must not re-run stream_events")

    agent = FakeAgent()
    ends = []
    streaming.run_agent_turn(
        agent,
        "t",
        None,
        checkpoint_id="cid-input",
        handle_interrupts=lambda _: None,
        callbacks={
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: None,
            "on_message_end": lambda t: ends.append(t),
        },
    )
    assert agent.stream_calls == []
    assert ends == ["saved-hello"]


def test_filter_pending_interrupts_skips_resolved():
    intr = type("I", (), {"value": {"action_requests": [{"name": "execute", "args": {"command": "ls"}}]}})()
    key = streaming.interrupt_action_key({"name": "execute", "args": {"command": "ls"}})
    assert streaming.filter_pending_interrupts([intr], {key}) == []
    assert len(streaming.filter_pending_interrupts([intr], set())) == 1


def test_run_agent_turn_abandon_calls_finalize():
    class _Stream:
        interrupted = True
        interrupts = [type("I", (), {"value": {"action_requests": [{"name": "execute", "args": {}}]}})()]
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    class FakeAgent:
        checkpointer = None
        finalized = False

        def stream_events(self, payload, *, version, config, control=None):
            return _Stream()

    agent = FakeAgent()
    import src.commands as cmd

    original = cmd.finalize_turn

    def track_finalize(a, t):
        agent.finalized = True
        return original(a, t)

    cmd.finalize_turn = track_finalize
    try:
        ok = streaming.run_agent_turn(
            agent,
            "t",
            "hi",
            handle_interrupts=lambda _: None,
            callbacks={
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": lambda d: None,
            },
        )
    finally:
        cmd.finalize_turn = original

    assert ok is False
    assert agent.finalized is True


# ---------------------------------------------------------------------------
# tui-ux6 #03 — Esc 真切断：RunControl drain（ADR-0008）
# ---------------------------------------------------------------------------


class _DrainCtl:
    """假 control：记录 request_drain 调用。"""

    def __init__(self):
        self.drain_calls = 0
        self.reason = None

    def request_drain(self, reason):
        self.drain_calls += 1
        self.reason = reason


class _DrainStream:
    """假 stream：对齐真实 Pregel——drain 请求后的下一个 yield 边界抛 GraphDrained。

    检查点必须放在 yield 之后（生成器恢复时求值）：消费层在取到 item 的循环体里才请求
    drain，早于下一次 next()；若检查点在两个 yield 之间，会在 drain 请求之前被求值
    （off-by-one），GraphDrained 永远不触发。
    """

    def __init__(self, ctl):
        self.ctl = ctl

    def interleave(self, *kinds):
        yield ("messages", _Msg("ab"))
        if self.ctl.drain_calls > 0:
            from langgraph.errors import GraphDrained

            raise GraphDrained("user-cancel")
        yield ("messages", _Msg("cd"))
        if self.ctl.drain_calls > 0:
            from langgraph.errors import GraphDrained

            raise GraphDrained("user-cancel")


def test_consume_stream_cancel_requests_drain_and_suppresses_callbacks():
    """取消命中 → request_drain("user-cancel") 恰好一次 + 后续回调全部抑制 + GraphDrained 透传。

    时序对齐真实图：flag 在 item 1 收尾（on_message_end）后翻转；item 2 取出时
    top-check 请求 drain 并抑制 item 2 全部回调；再取下一项时流按图语义抛
    GraphDrained（_DrainStream 在 drain 已请求且无更多 item 时模拟）。
    """
    from langgraph.errors import GraphDrained

    ctl = _DrainCtl()
    flags = {"cancelled": False}
    deltas = []
    segments = []
    tool_calls = []
    cancelled_at = []

    def on_cancelled():
        cancelled_at.append(True)

    stream = _DrainStream(ctl)
    with pytest.raises(GraphDrained):
        streaming.consume_stream_events(
            stream,
            {
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda n, *a: tool_calls.append(n),
                "on_message_delta": lambda d: deltas.append(d),
                "on_message_end": lambda seg: (
                    flags.__setitem__("cancelled", True),
                    segments.append(seg),
                ),
            },
            is_cancelled=lambda: flags["cancelled"],
            on_cancelled=on_cancelled,
            control=ctl,
        )
    assert ctl.drain_calls == 1
    assert ctl.reason == "user-cancel"
    assert deltas == ["a", "b"]  # 只消费到 item 1 的 delta
    assert segments == ["ab"]  # item 1 的 on_message_end 在取消前已发生
    assert tool_calls == []  # item 2（tool_calls）被 drain 抑制
    assert cancelled_at == [True]  # on_cancelled 只触发一次


def test_consume_stream_cancel_mid_delta_suppresses_partial_segment():
    """取消在 delta 循环中途命中 → 请求 drain 后本条 segment 不再发 on_message_end，
    后续 delta 不再消费，GraphDrained 透传。"""
    from langgraph.errors import GraphDrained

    class _MidDrainStream:
        def interleave(self, *kinds):
            yield ("messages", _Msg("abcd"))
            if ctl2.drain_calls > 0:
                raise GraphDrained("user-cancel")

    ctl2 = _DrainCtl()
    flags = {"cancelled": False}
    deltas = []
    segments = []

    def on_message_delta(d):
        deltas.append(d)
        if len(deltas) == 2:
            flags["cancelled"] = True

    with pytest.raises(GraphDrained):
        streaming.consume_stream_events(
            _MidDrainStream(),
            {
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": on_message_delta,
                "on_message_end": lambda seg: segments.append(seg),
            },
            is_cancelled=lambda: flags["cancelled"],
            control=ctl2,
        )
    assert ctl2.drain_calls == 1
    assert deltas == ["a", "b"]  # 取消后 "c"/"d" 不再消费
    assert segments == []  # 部分 segment 的 on_message_end 被抑制


def test_consume_stream_cancel_without_control_keeps_legacy_semantics():
    """control=None：取消命中立即返回（旧语义），不请求 drain、不吞异常。"""
    ctl = _DrainCtl()
    flags = {"cancelled": False}
    deltas = []
    segments = []

    stream = _DrainStream(ctl)
    consumed = streaming.consume_stream_events(
        stream,
        {
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: deltas.append(d),
            "on_message_end": lambda seg: (
                flags.__setitem__("cancelled", True),
                segments.append(seg),
            ),
        },
        is_cancelled=lambda: flags["cancelled"],
        control=None,
    )
    assert ctl.drain_calls == 0
    assert deltas == ["a", "b"]
    assert segments == ["ab"]
    assert consumed == 2  # 旧语义立即返回，不继续消费 item 2


def test_run_agent_turn_drain_stops_after_single_slow_tool():
    """e2e（对标 scratch/probe_drain.py）：慢工具运行中取消 → drain 停图，
    第二次模型调用不发生，run_agent_turn 返回 False（cancel 而非异常上抛）。"""
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool

    @tool
    def slow(name: str) -> str:
        """Slow tool for drain e2e."""
        time.sleep(2.0)
        return "tool done"

    class TProbe(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            model_calls.append(1)
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model_calls: list = []
    model = TProbe(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "slow", "args": {"name": "x"}, "id": "c1"}]),
            AIMessage(content="finished"),
        ],
        messages=[],
    )
    agent = create_deep_agent(model=model, tools=[slow], checkpointer=None)

    flags = {"cancelled": False}

    def cancel_soon():
        time.sleep(0.3)
        flags["cancelled"] = True

    th = threading.Thread(target=cancel_soon)
    th.start()
    t0 = time.monotonic()
    ok = streaming.run_agent_turn(
        agent,
        "t-drain-e2e",
        "go",
        handle_interrupts=lambda _: None,
        callbacks={
            "on_subagent": lambda *a: None,
            "on_tool_call": lambda *a: None,
            "on_message_delta": lambda d: None,
        },
        is_cancelled=lambda: flags["cancelled"],
    )
    th.join(timeout=5)
    wall = time.monotonic() - t0
    assert ok is False
    # 判别性断言：旧代码会跑满两轮模型调用（慢工具后还有第二次 LLM 调用）；
    # drain 语义下第二次模型调用不发生。
    assert len(model_calls) == 1
    assert wall < 3.5, f"drain 未真切断：wall={wall:.2f}s"
