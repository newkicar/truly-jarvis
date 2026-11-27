"""① TurnPresenter：per-turn 流式状态收拢（架构评审候选①第二步）。"""

from src.permissions import PROXY_REVIEW_LAST_KEY
from src.tui_turn import TurnPresenter
from tests.test_tui import FakeAgent


def test_presenter_holds_per_turn_state():
    """构造即快照 start_mode；可变状态归 presenter 而非闭包。"""
    class _App:
        permission_state = {"mode": "plan"}
        thread_id = "stub-t1"

        def call_from_thread(self, fn, *args):
            return fn(*args)

        def query_one(self, sel, typ):
            return None

    p = TurnPresenter(_App(), user_input="hi", checkpoint_id=None)
    assert p.start_mode == "plan"
    assert p.user_input == "hi"
    assert p.stream_active is False
    assert p.cancel_notified is False
    assert not p.cancelled()  # 无 worker 时视为未取消


def test_callbacks_dict_has_all_six_keys():
    class _App:
        permission_state = {}
        thread_id = "stub-t2"

        def call_from_thread(self, fn, *args):
            return fn(*args)

        def query_one(self, sel, typ):
            return None

    p = TurnPresenter(_App(), user_input=None, checkpoint_id=None)
    cb = p.callbacks()
    assert set(cb) == {"on_subagent", "on_tool_call", "on_message_delta", "on_message_end", "on_status", "on_reasoning_end"}


async def test_app_stream_agent_delegates_to_presenter(monkeypatch):
    """_stream_agent 薄壳化：委托 TurnPresenter.run。"""
    from unittest.mock import patch

    from src.tui import JarvisApp

    app = JarvisApp(None, FakeAgent(reply="好"), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        created: list[TurnPresenter] = []
        orig_init = TurnPresenter.__init__

        def spy_init(self, *a, **k):
            orig_init(self, *a, **k)
            created.append(self)

        with patch.object(TurnPresenter, "__init__", spy_init), \
             patch.object(TurnPresenter, "run", lambda self: setattr(self, "ran", True)):
            from src.tui import JarvisTextArea

            inp = app.query_one(JarvisTextArea)
            inp.focus()
            inp.text = "你好"
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause()
                if any(getattr(p, "ran", False) for p in created):
                    break
        assert created and any(getattr(p, "ran", False) for p in created)


# ----------------------------------------------------------------------
# #20: TUI ⚡ proxy-review 放行标记（TurnPresenter.on_tool_call 呈现）
# ----------------------------------------------------------------------



class _FakeLog:
    """TurnPresenter.log 替身：write（普通单行）/ write_tool_entry（可展开条目）。"""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.entries: list[tuple[str, str]] = []

    def write(self, text: str) -> None:
        self.lines.append(text)

    def write_tool_entry(self, collapsed: str, expanded: str) -> None:
        self.entries.append((collapsed, expanded))


def _make_presenter(state: dict, tid: str = "t1"):
    class _App:
        def __init__(self, state, log):
            self.permission_state = state
            self.thread_id = tid
            self.log = log

        def call_from_thread(self, fn, *args):
            return fn(*args)

        def query_one(self, sel, typ):
            return self.log

        def notify(self, *a, **k):
            pass

        def _refresh_todos_panel(self) -> None:
            pass

    log = _FakeLog()
    app = _App(state, log)
    return TurnPresenter(app, user_input="hi", checkpoint_id=None), log


def _allow_record(tool: str = "execute", tid: str = "t1") -> dict:
    return {"tool": tool, "outcome": "allow", "rationale": "低危只读", "thread_id": tid}


def test_tui_turn_marker_long_arg_allow() -> None:
    """长参数（>80）+ allow → 走可展开条目，折叠/展开态都带 ⚡ 标记。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record()})
    p.on_tool_call("execute", "x" * 120, False, None, 0)
    assert len(log.entries) == 1
    collapsed, expanded = log.entries[0]
    assert "⚡ proxy-review 放行 低危只读" in collapsed
    assert "⚡ proxy-review 放行 低危只读" in expanded
    assert log.lines == []


def test_tui_turn_marker_short_no_output_allow() -> None:
    """短参数 + 无输出 + allow → 普通单行调用，行内带 ⚡ 标记。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record()})
    p.on_tool_call("execute", "git status", False, None, 0)
    assert log.entries == []
    assert "⚡ proxy-review 放行 低危只读" in log.lines[0]


def test_tui_turn_marker_short_with_output_allow() -> None:
    """短参数但有输出 + allow → 走可展开条目，条目带 ⚡ 标记。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record()})
    p.on_tool_call("execute", "git status", False, "total 1", 0)
    assert len(log.entries) == 1
    collapsed, expanded = log.entries[0]
    assert "⚡" in collapsed and "⚡" in expanded
    assert log.lines == []


def test_tui_turn_no_marker_on_error() -> None:
    """err=True → 失败条目，不带 ⚡ 标记（放行标记不掩盖失败）。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record()})
    p.on_tool_call("execute", "x" * 120, True, None, 0)
    assert len(log.entries) == 1
    collapsed, expanded = log.entries[0]
    assert "⚡" not in collapsed and "⚡" not in expanded
    assert log.lines == []


def test_tui_turn_no_marker_when_outcome_ask() -> None:
    """outcome=ask（回落人工审批）→ 不呈现 ⚡ 放行标记。"""
    rec = dict(_allow_record())
    rec["outcome"] = "ask"
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: rec})
    p.on_tool_call("execute", "x" * 120, False, None, 0)
    assert len(log.entries) == 1
    assert "⚡" not in log.entries[0][0]


def test_tui_turn_no_marker_on_tool_mismatch() -> None:
    """记录工具是 write_file，本次调用 execute → 跨工具不呈现。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record(tool="write_file")})
    p.on_tool_call("execute", "x" * 120, False, None, 0)
    assert len(log.entries) == 1
    assert "⚡" not in log.entries[0][0]


def test_tui_turn_no_marker_on_thread_mismatch() -> None:
    """记录属于 t2，本轮在 t1 → 跨线程不呈现。"""
    p, log = _make_presenter({PROXY_REVIEW_LAST_KEY: _allow_record(tid="t2")})
    p.on_tool_call("execute", "x" * 120, False, None, 0)
    assert len(log.entries) == 1
    assert "⚡" not in log.entries[0][0]


def test_tui_turn_no_marker_without_record() -> None:
    """state 无裁决记录（缺省 {}）→ 无 ⚡ 标记。"""
    p, log = _make_presenter({})
    p.on_tool_call("execute", "x" * 120, False, None, 0)
    assert len(log.entries) == 1
    assert "⚡" not in log.entries[0][0]
