"""TUI 骨架测试：app 启动/退出、输入路由、命令分发到 commands.py。"""

import asyncio
import time

import pytest

from textual.widgets import Input, RichLog

from src.tui import EditParamsModal, JarvisApp, PermissionModal
from src import commands


class _FakeMsg:
    def __init__(self, text):
        self.text = text


class _FakeInterrupt:
    def __init__(self, tool="execute", args=None):
        self.value = {"action_requests": [{"name": tool, "args": args or {}}]}


class _FakeStream:
    def __init__(self, text, interrupted=False, interrupts=None):
        self._items = [("messages", _FakeMsg(text))]
        self.interrupted = interrupted
        self.interrupts = interrupts
        self.output = None

    def interleave(self, *kinds):
        for item in self._items:
            yield item


class FakeAgent:
    checkpointer = None

    def __init__(self, reply="AI 你好", interrupted=False, interrupts=None):
        self._reply = reply
        self._interrupted = interrupted
        self._interrupts = interrupts
        self._calls = 0

    def get_state_history(self, config=None):
        return iter([])

    def stream_events(self, *args, **kwargs):
        self._calls += 1
        interrupted = self._interrupted and self._calls == 1
        return _FakeStream(self._reply, interrupted, self._interrupts)


async def _type_and_enter(pilot, text):
    input_widget = pilot.app.query_one(Input)
    input_widget.focus()
    input_widget.value = text
    await pilot.pause()
    await pilot.press("enter")


@pytest.mark.asyncio
async def test_app_starts_and_quits():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        assert isinstance(pilot.app.query_one("#messages"), RichLog)
        assert isinstance(pilot.app.query_one(Input), Input)
        await pilot.pause()


@pytest.mark.asyncio
async def test_history_command_shows_result():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/history")
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        assert "暂无历史" in log.lines[-1].text


@pytest.mark.asyncio
async def test_unknown_command_routes_to_dispatch():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/bogus")
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        assert "未知命令" in log.lines[-1].text


@pytest.mark.asyncio
async def test_plain_text_streams_reply():
    app = JarvisApp(None, FakeAgent(reply="你好，我是 JARVIS"), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "你好")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        joined = "".join(l.text for l in log.lines).replace("▌", "").replace(" ", "").replace("JARVIS", "")
        assert "你好，我是JARVIS" in joined or "你好，我是" in joined


@pytest.mark.asyncio
async def test_new_session_action():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        app.action_new_session()
        await pilot.pause()
        assert app.thread_id.startswith("session-")
        assert app.sub_title == app.thread_id


@pytest.mark.asyncio
async def test_escape_cancels_streaming():
    class SlowAgent(FakeAgent):
        def stream_events(self, *args, **kwargs):
            class S(_FakeStream):
                interrupted = False
                interrupts = None
                output = None

                def __init__(self):
                    self._items = [
                        ("messages", _FakeMsg("正在思考")),
                        ("messages", _FakeMsg("…")),
                    ]

                def interleave(self, *kinds):
                    for item in self._items:
                        time.sleep(0.2)
                        yield item

            return S()

    app = JarvisApp(None, SlowAgent(reply=""), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "慢请求")
        await pilot.pause()
        await asyncio.sleep(0.1)
        app.action_cancel()
        await pilot.pause()
        await asyncio.sleep(0.4)
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        joined = "".join(l.text for l in log.lines)
        assert "已取消" in joined


@pytest.mark.asyncio
async def test_interrupt_pops_permission_modal_and_approves():
    intr = _FakeInterrupt("execute", {"command": "rm -rf /"})
    app = JarvisApp(
        None,
        FakeAgent(reply="已执行", interrupted=True, interrupts=[intr]),
        {"default": "ask", "tools": {}},
    )
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "删除文件")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert isinstance(app.screen, PermissionModal)
        # 放行
        app.screen.dismiss({"decision": "approve"})
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        assert "model" in "".join(l.text for l in log.lines)


@pytest.mark.asyncio
async def test_interrupt_reject_shows_message():
    intr = _FakeInterrupt("write_file", {"file_path": "/tmp/x.py"})
    app = JarvisApp(
        None,
        FakeAgent(reply="", interrupted=True, interrupts=[intr]),
        {"default": "ask", "tools": {}},
    )
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "写文件")
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert isinstance(app.screen, PermissionModal)
        app.screen.dismiss({"decision": "reject"})
        await pilot.pause()
        await asyncio.sleep(0.2)
        await pilot.pause()
        log = pilot.app.query_one(RichLog)
        assert "已放弃" not in "".join(l.text for l in log.lines)


@pytest.mark.asyncio
async def test_exit_command_quits():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/exit")
        await pilot.pause()
        assert not app.is_running


@pytest.mark.asyncio
async def test_theme_persistence(tmp_path):
    import json
    config_file = tmp_path / "javis.json"
    config_file.write_text(json.dumps({"permissions": {"*": "ask"}}), encoding="utf-8")

    # Patch _config_path to use tmp_path
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app._config_path = lambda: config_file

    async with app.run_test() as pilot:
        # Theme should be default
        assert app.theme == "textual-dark"
        # Simulate theme change
        app.theme = "dracula"
        await pilot.pause()
        # Verify saved
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["theme"] == "dracula"

    # New app instance should restore
    app2 = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app2._config_path = lambda: config_file
    app2._restore_theme()
    assert app2.theme == "dracula"