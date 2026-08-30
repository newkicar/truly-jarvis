"""streaming 消费层测试。"""
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

        def stream_events(self, payload, *, version, config):
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
    assert config["configurable"] == {"thread_id": "t", "checkpoint_id": "cid-0000000-aaaa"}


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

        def stream_events(self, payload, *, version, config):
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

        def stream_events(self, payload, *, version, config):
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
