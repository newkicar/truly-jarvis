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
