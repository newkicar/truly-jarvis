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


def test_consume_stream_on_thinking_optional_key():
    """工单 06 共享 seam：可选第 6 键 on_thinking（v3 messages 投影 .reasoning 增量）。"""

    class _MsgT:
        def __init__(self, text, thinking):
            self.text = list(text)
            self.reasoning = list(thinking)

    events = []
    stream = _Stream([("messages", _MsgT("答案", "思考片段"))])
    streaming.consume_stream_events(
        stream,
        {
            "on_message_delta": lambda d: events.append(("delta", d)),
            "on_message_end": lambda s: events.append(("end", s)),
            "on_thinking": lambda d: events.append(("think", d)),
        },
    )
    # 思考增量在正文之前（模型先 reasoning 后 content）
    thinks = [t for k, t in events if k == "think"]
    assert "".join(thinks) == "思考片段"
    assert events.index(("think", "思")) < events.index(("delta", "答"))
    assert ("end", "答案") in events


def test_consume_stream_without_on_thinking_no_behavior_change():
    """未传 on_thinking = 思考通道不启用（CLI/TUI 现状零行为变化，TUI 已知问题①不回退）。"""

    class _MsgT:
        def __init__(self, text, thinking):
            self.text = list(text)
            self.reasoning = list(thinking)

    events = []
    stream = _Stream([("messages", _MsgT("答案", "思考"))])
    streaming.consume_stream_events(
        stream,
        {
            "on_message_delta": lambda d: events.append(("delta", d)),
            "on_message_end": lambda s: events.append(("end", s)),
        },
    )
    assert all(k != "think" for k, _ in events)
    assert ("end", "答案") in events


def test_consume_stream_on_thinking_delta_not_cancelled():
    class _MsgT:
        def __init__(self):
            self.text = []
            self.reasoning = list("长思考")

    events = []
    cancelled = {"flag": False}
    stream = _Stream([("messages", _MsgT())])
    streaming.consume_stream_events(
        stream,
        {
            "on_message_delta": lambda d: events.append(("delta", d)),
            "on_thinking": lambda d: events.append(("think", d)) or None,
        },
        is_cancelled=lambda: cancelled["flag"],
    )
    # 未取消时思考全量到达（取消抑制语义同正文 delta 通道）
    assert ("think", "长") in events


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

    assert ok.ok is False
    assert agent.finalized is True


def test_run_agent_turn_reject_counts_in_tool_calls():
    """#goal 05: 全 reject 轮 _count_rejected_actions 补计 tool_calls_count（续跑门能看见）。"""
    import src.commands as cmd

    class _Intr:
        value = {"action_requests": [{"name": "execute", "args": {"command": "echo hi"}}]}

    class _StreamIntr:
        interrupted = True
        interrupts = [_Intr()]
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    class _StreamOk:
        interrupted = False
        interrupts = None
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    calls = {"n": 0}

    class FakeAgent:
        checkpointer = None

        def stream_events(self, payload, *, version, config, control=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _StreamIntr()
            return _StreamOk()

    agent = FakeAgent()
    original = cmd.finalize_turn
    cmd.finalize_turn = lambda *a, **kw: None
    try:
        ok = streaming.run_agent_turn(
            agent,
            "t",
            "hi",
            handle_interrupts=lambda intr: {"decisions": [{"type": "reject"}]},
            callbacks={
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": lambda d: None,
            },
        )
    finally:
        cmd.finalize_turn = original

    assert ok.ok is True
    assert ok.outcome == "complete"
    assert ok.tool_calls_count == 1


def test_run_agent_turn_filtered_decisions_skip_reject_count():
    """#goal 05 守卫：decisions 数 ≠ action 数（TUI filter 后）→ 整体跳过，不误计。"""
    import src.commands as cmd

    class _Intr:
        value = {
            "action_requests": [
                {"name": "execute", "args": {"command": "echo a"}},
                {"name": "execute", "args": {"command": "echo b"}},
            ]
        }

    class _StreamIntr:
        interrupted = True
        interrupts = [_Intr()]
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    class _StreamOk:
        interrupted = False
        interrupts = None
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    calls = {"n": 0}

    class FakeAgent:
        checkpointer = None

        def stream_events(self, payload, *, version, config, control=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _StreamIntr()
            return _StreamOk()

    agent = FakeAgent()
    original = cmd.finalize_turn
    cmd.finalize_turn = lambda *a, **kw: None
    try:
        # 2 actions vs 1 decision → 守卫触发，不计数
        ok = streaming.run_agent_turn(
            agent,
            "t",
            "hi",
            handle_interrupts=lambda intr: {"decisions": [{"type": "reject"}]},
            callbacks={
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": lambda d: None,
            },
        )
    finally:
        cmd.finalize_turn = original

    assert ok.ok is True
    assert ok.outcome == "complete"
    assert ok.tool_calls_count == 0


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
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
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
    assert ok.ok is False
    # 判别性断言：旧代码会跑满两轮模型调用（慢工具后还有第二次 LLM 调用    # drain 语义下第二次模型调用不发生。
    # 判别断言：第二次 LLM 调用绝不发生。tui-ux10 看门狗使 drain 瞬间前移，
    # 第一次调用也可能未完成即被取消（0 次），故断言 <= 1。
    assert len(model_calls) <= 1
    assert wall < 3.5, f"drain 未真切断：wall={wall:.2f}s"

def test_drain_watchdog_requests_before_tool_end_item_arrives():  # noqa: C901
    """tui-ux10：慢工具运行中取消（无 item 到达窗口），看门狗立即 request_drain——
    不依赖 tool_end item 到达时机（CI langgraph 1.2.16 事件发射时序回归防御）。"""
    from unittest import mock

    import langgraph.runtime as _lg_runtime
    from deepagents import create_deep_agent
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool

    @tool
    def slow(name: str) -> str:
        """Slow tool for drain watchdog e2e."""
        time.sleep(2.0)
        return "tool done"

    class TProbe(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            model_calls.append(1)
            if len(model_calls) == 1:
                time.sleep(2.0)  # 模拟 LLM 首响延迟：取消后该窗口内无任何 item 发射
            return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model_calls: list = []
    model = TProbe(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "slow", "args": {"name": "x"}, "id": "c2w"}]),
            AIMessage(content="finished"),
        ],
        messages=[],
    )
    agent = create_deep_agent(model=model, tools=[slow], checkpointer=None)

    req = {"calls": 0, "first_at": None}
    t0 = {"cancel": None}

    class _SpyRunControl:
        def __init__(self):
            self._reason = None

        def request_drain(self, reason="user-cancel"):
            self._reason = reason
            req["calls"] += 1
            if req["first_at"] is None:
                req["first_at"] = time.monotonic()

        @property
        def drain_requested(self):
            return self._reason is not None

        @property
        def drain_reason(self):
            return self._reason

    flags = {"cancelled": False}

    def cancel_soon():
        time.sleep(0.3)
        flags["cancelled"] = True
        t0["cancel"] = time.monotonic()

    th = threading.Thread(target=cancel_soon)
    with mock.patch.object(_lg_runtime, "RunControl", return_value=_SpyRunControl()):
        th.start()
        ok = streaming.run_agent_turn(
            agent,
            "t-watchdog-e2e",
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
    assert ok.ok is False
    # 0 = 取消早于首模型调用启动（看门狗抢先 drain），同样合法；
    # 判别性在于绝不超过 1（无修复时 CI 上会跑满 2 次模型调用）。
    assert len(model_calls) <= 1
    assert req["calls"] >= 1
    # 无看门狗：取消（0.3s）后首次 drain 请求在首个 item 到达时（模型 2s 延迟之后，
    # 距取消 >1.0s）；有看门狗：取消命中后 ~50ms 内即请求 drain。
    assert req["first_at"] - t0["cancel"] < 1.0


def test_format_agent_error_id_string_branch():
    """网关 "Expected 'id' to be a string." / content part 类 400 → 专门指引
    （已自动清洗 + 新会话兜底），不再裸吐 BadRequest 通用文案。"""
    from src.streaming import format_agent_error

    class Fake400(Exception):
        pass

    out = format_agent_error(Fake400("openai BadRequestError: 400 Expected 'id' to be a string."))
    assert "已自动清洗" in out
    assert "/delete-session" in out
    out2 = format_agent_error(Fake400("Unsupported content part type: 'tool_call'"))
    assert "已自动清洗" in out2


def test_format_agent_error_context_overflow_branch():
    """上下文超限 400 → 专属 overflow 文案，优先于通用 400 分支（msg 含 "400" 也不误配）。"""
    from src.streaming import format_agent_error

    class Fake400(Exception):
        pass

    out = format_agent_error(
        Fake400(
            "Error code: 400 - This model maximum context length is 131072 tokens. "
            "However, your prompt contains at least 131073 input tokens. "
            "(parameter=input_tokens, value=131073)"
        )
    )
    assert "上下文超限" in out
    assert "API 请求失败" not in out
    assert ".jarvis/conversation_history" in out


def test_format_agent_error_generic_400_branch_unchanged():
    """普通 400（非超限）仍走通用文案，overflow 分支不误吞。"""
    from src.streaming import format_agent_error

    class Fake400(Exception):
        pass

    out = format_agent_error(Fake400("API request failed: 400 Bad Request: model not found"))
    assert "API 请求失败" in out
    assert "常见原因" in out
    assert "上下文超限" not in out


def test_run_agent_turn_when_predicate_sees_thread_local_tid():
    """Issue #8：run_agent_turn 入口 set 的 thread-local tid 在 when 求值点（_run_stream 同线程）可见。"""
    import src.commands as cmd
    from src.jump_in_queue import get_current_thread_id
    from src.permissions import build_permission_interrupts, proxy_on

    interrupt_on, state = build_permission_interrupts({})
    proxy_on(state, "t8")
    when_exec = interrupt_on["execute"]["when"]
    seen = {}

    class _Req:
        def __init__(self, args):
            self.tool_call = {"name": "execute", "args": args}

    class _Stream:
        interrupted = False
        interrupts = None
        output = None

        def interleave(self, *kinds):
            if False:
                yield

    class FakeAgent:
        checkpointer = None

        def stream_events(self, payload, *, version, config, control=None):
            seen["tid"] = get_current_thread_id()
            seen["safe"] = when_exec(_Req({"command": "git status"}))
            seen["danger"] = when_exec(_Req({"command": "rm -rf /"}))
            return _Stream()

    agent = FakeAgent()
    original = cmd.finalize_turn
    cmd.finalize_turn = lambda *a, **kw: None
    try:
        ok = streaming.run_agent_turn(
            agent, "t8", "hi",
            handle_interrupts=lambda _: None,
            callbacks={
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": lambda d: None,
            },
            permission_state=state,
        )
    finally:
        cmd.finalize_turn = original

    assert ok.ok is True
    assert seen["tid"] == "t8"
    assert seen["safe"] is False
    assert seen["danger"] is True
    assert get_current_thread_id() is None  # finally 成对清理

# ---- #32: 上下文超限自动 /compact 反应层（run_agent_turn 公共接缝）----


class _OverflowAgent:
    """前 fail_times 次 stream 尝试抛 overflow 异常，之后返回空流。"""

    checkpointer = None

    def __init__(self, fail_times: int = 1):
        self.fail_times = fail_times
        self.stream_calls: list = []
        self.compact_calls: list = []
        self.compact_result = "已压缩上下文：原 4 条消息 → 摘要 10 字，旧历史已覆盖（仅消息层）"

    def stream_events(self, payload, *, version, config, control=None):
        self.stream_calls.append(payload)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ValueError(
                "Error code: 400 - This model maximum context length is 131072 tokens. "
                "However, your prompt contains at least 131073 input tokens."
            )
        return _Stream([])


def _run_with_auto_compact(agent, user_input, statuses, **kwargs):
    """run_agent_turn + monkeypatch compact（仅记录，不触真模型）。"""
    import src.commands as cmd

    orig_compact = cmd.compact

    def fake_compact(a, t, guide=None):
        agent.compact_calls.append(t)
        return agent.compact_result

    cmd.compact = fake_compact
    try:
        return streaming.run_agent_turn(
            agent,
            "t32",
            user_input,
            handle_interrupts=lambda _: None,
            callbacks={
                "on_subagent": lambda *a: None,
                "on_tool_call": lambda *a: None,
                "on_message_delta": lambda d: None,
                "on_status": statuses.append,
            },
            **kwargs,
        )
    finally:
        cmd.compact = orig_compact


def test_run_agent_turn_auto_compact_recovers_overflow():
    """#32: 超限 → 自动 /compact 成功 → 重放用户输入、任务继续 + UI 提示。"""
    agent = _OverflowAgent(fail_times=1)
    statuses: list = []
    ok = _run_with_auto_compact(agent, "请继续任务", statuses)
    assert ok.ok is True
    assert agent.compact_calls == ["t32"]
    assert any("已自动压缩" in s for s in statuses)
    assert len(agent.stream_calls) == 2
    assert agent.stream_calls[1] == {"messages": [{"role": "user", "content": "请继续任务"}]}


def test_run_agent_turn_auto_compact_second_overflow_falls_back():
    """#32: 压缩后仍超限（预算 1 次）→ 提示 + 上抛原异常（不死循环）。"""
    agent = _OverflowAgent(fail_times=99)
    statuses: list = []
    with pytest.raises(ValueError, match="maximum context length"):
        _run_with_auto_compact(agent, "hi", statuses, auto_compact_max_attempts=1)
    assert len(agent.compact_calls) == 1
    assert any("自动压缩后仍超限" in s for s in statuses)


def test_run_agent_turn_auto_compact_failure_falls_back():
    """#32: compact 返回失败文案 → 提示失败文本、不再重试 stream、异常上抛。"""
    agent = _OverflowAgent(fail_times=99)
    agent.compact_result = "消息太少（2 条；至少 4 条），无需压缩"
    statuses: list = []
    with pytest.raises(ValueError, match="maximum context length"):
        _run_with_auto_compact(agent, "hi", statuses)
    assert len(agent.compact_calls) == 1
    assert len(agent.stream_calls) == 1
    assert any("消息太少" in s for s in statuses)


def test_run_agent_turn_auto_compact_disabled_no_compact():
    """#32: 开关关 → compact 零调用，overflow 直接上抛。"""
    agent = _OverflowAgent(fail_times=99)
    statuses: list = []
    with pytest.raises(ValueError, match="maximum context length"):
        _run_with_auto_compact(agent, "hi", statuses, auto_compact_on_overflow=False)
    assert not agent.compact_calls
    assert len(agent.stream_calls) == 1


def test_run_agent_turn_overflow_without_user_input_no_compact():
    """#32: replay 路径（user_input=None）超限 → 不自动 compact，直接上抛。"""
    agent = _OverflowAgent(fail_times=99)
    statuses: list = []
    with pytest.raises(ValueError, match="maximum context length"):
        _run_with_auto_compact(agent, None, statuses)
    assert not agent.compact_calls
