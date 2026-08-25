"""① TurnPresenter：per-turn 流式状态收拢（架构评审候选①第二步）。"""

from src.tui_turn import TurnPresenter

from tests.test_tui import FakeAgent


def test_presenter_holds_per_turn_state():
    """构造即快照 start_mode；可变状态归 presenter 而非闭包。"""
    class _App:
        permission_state = {"mode": "plan"}

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


def test_callbacks_dict_has_all_five_keys():
    class _App:
        permission_state = {}

        def call_from_thread(self, fn, *args):
            return fn(*args)

        def query_one(self, sel, typ):
            return None

    p = TurnPresenter(_App(), user_input=None, checkpoint_id=None)
    cb = p.callbacks()
    assert set(cb) == {"on_subagent", "on_tool_call", "on_message_delta", "on_message_end", "on_status"}


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
            from textual.widgets import Input

            inp = app.query_one(Input)
            inp.focus()
            inp.value = "你好"
            await pilot.pause()
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause()
                if any(getattr(p, "ran", False) for p in created):
                    break
        assert created and any(getattr(p, "ran", False) for p in created)
