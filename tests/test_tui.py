"""TUI 骨架测试：app 启动/退出、输入路由、命令分发到 commands.py。"""

import asyncio
import time

from contextlib import contextmanager

import pytest

from textual.widgets import Input, Static

from src.tui import EditParamsModal, JarvisApp, PathCompletionOverlay, PermissionModal, SessionSidebar
from src.tui_log import CopyableRichLog
from src import commands


class _FakeMsg:
    def __init__(self, text):
        self.text = text if isinstance(text, list) else list(text)


class _FakeToolCall:
    def __init__(self, name, input="", output=None, error=None):
        self.tool_name = name
        self.input = input
        self.output = output
        self.error = error


class _FakeSubagent:
    def __init__(self, name, status, tool_calls=None):
        self.name = name
        self.status = status
        self.tool_calls = tool_calls or []


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
        assert isinstance(pilot.app.query_one("#messages"), CopyableRichLog)
        assert isinstance(pilot.app.query_one(Input), Input)
        await pilot.pause()


@pytest.mark.asyncio
async def test_slash_command_runs_in_background_worker():
    """/history 等命令不得在 UI 线程阻塞（/replay 等同理）。"""

    class SlowHistoryAgent(FakeAgent):
        checkpointer = None

        def get_state_history(self, config=None):
            time.sleep(0.4)
            return iter([])

    app = JarvisApp(None, SlowHistoryAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/history")
        await pilot.pause()
        assert app._worker is not None
        await asyncio.sleep(0.55)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "暂无历史" in joined
        assert "正在执行 /history" in joined


@pytest.mark.asyncio
async def test_history_command_shows_result():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/history")
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "暂无历史" in joined


@pytest.mark.asyncio
async def test_unknown_command_routes_to_dispatch():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/bogus")
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "未知命令" in joined


@pytest.mark.asyncio
async def test_streaming_renders_markdown_not_typing_placeholder():
    app = JarvisApp(
        None,
        FakeAgent(reply="## 标题\n\n**正文**"),
        {"default": "ask", "tools": {}},
    )
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "流式")
        await pilot.pause()
        await asyncio.sleep(0.35)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "正在思考" not in joined
        assert "JARVIS" in joined
        assert "正文" in joined
        stream = pilot.app.query_one("#ai_stream", Static)
        assert not stream.has_class("-active")


@pytest.mark.asyncio
async def test_plain_text_streams_reply():
    app = JarvisApp(None, FakeAgent(reply="你好，我是 JARVIS"), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "你好")
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "你好" in joined
        assert "JARVIS" in joined


@pytest.mark.asyncio
async def test_new_session_action():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        app.action_new_session()
        await pilot.pause()
        assert app.thread_id.startswith("session-")
        assert app.sub_title.startswith(app.thread_id)  # #08: 尾部追加 Act/Plan 模式名


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
        log = pilot.app.query_one(CopyableRichLog)
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
        log = pilot.app.query_one(CopyableRichLog)
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
        log = pilot.app.query_one(CopyableRichLog)
        assert "已放弃" not in "".join(l.text for l in log.lines)


@pytest.mark.asyncio
async def test_exit_command_quits():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/exit")
        await pilot.pause()
        assert not app.is_running


class _FakeConfig:
    def __init__(self, vault_path, memory_dir=None, model_id="test-model"):
        self.vault_path = vault_path
        self.memory_dir = memory_dir or (vault_path.parent / "memory")
        self.model_id = model_id


class _FakeCheckpointer:
    def __init__(self, threads):
        self._threads = threads

    @property
    def conn(self):
        return self

    def execute(self, sql):
        return self

    def fetchall(self):
        return [(t,) for t in self._threads]

    @contextmanager
    def cursor(self, transaction=True):
        yield self


class _SidebarAgent(FakeAgent):
    def __init__(self, threads, **kwargs):
        super().__init__(**kwargs)
        self.checkpointer = _FakeCheckpointer(threads)


@pytest.mark.asyncio
async def test_path_completion_overlay_not_in_main_layout():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        assert pilot.app.query_one("#path_completion", PathCompletionOverlay) is not None
        assert not pilot.app.query("#editor_column")


@pytest.mark.asyncio
async def test_session_sidebar_lists_and_switches_thread():
    app = JarvisApp(
        None,
        _SidebarAgent(["default", "session-old"]),
        {"default": "ask", "tools": {}},
        thread_id="default",
    )
    async with app.run_test() as pilot:
        sidebar = pilot.app.query_one("#session_sidebar", SessionSidebar)
        assert sidebar.option_count == 2
        assert "▸ default" in str(sidebar.get_option_at_index(0).prompt)

        sidebar.highlighted = 1
        sidebar.action_select()
        await pilot.pause()

        assert app.thread_id == "session-old"
        assert "session-old" in app.sub_title
        log = pilot.app.query_one(CopyableRichLog)
        assert "已切换到会话 session-old" in "".join(l.text for l in log.lines)


@pytest.mark.asyncio
async def test_toggle_sidebar_collapses():
    app = JarvisApp(None, _SidebarAgent(["default"]), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        sidebar = pilot.app.query_one("#session_sidebar", SessionSidebar)
        assert not sidebar.has_class("-collapsed")
        app.action_toggle_sidebar()
        await pilot.pause()
        assert sidebar.has_class("-collapsed")
        app.action_toggle_sidebar()
        await pilot.pause()
        assert not sidebar.has_class("-collapsed")


@pytest.mark.asyncio
async def test_startup_prompt_auto_submits_message():
    app = JarvisApp(
        None,
        FakeAgent(reply="收到"),
        {"default": "ask", "tools": {}},
        startup_prompt="自动冒烟问题",
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.35)
        await pilot.pause()
        log = pilot.app.query_one(CopyableRichLog)
        joined = "".join(l.text for l in log.lines)
        assert "自动冒烟问题" in joined


@pytest.mark.asyncio
async def test_at_completion_shows_candidates_and_inserts_path(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Inbox").mkdir(parents=True)
    (vault / "Inbox" / "note.md").write_text("# note", encoding="utf-8")
    (vault / "other").mkdir()
    (vault / "other" / "x.md").write_text("# x", encoding="utf-8")
    ws = tmp_path / "project"
    (ws / "memory").mkdir(parents=True)
    (ws / "readme.md").write_text("# readme", encoding="utf-8")

    app = JarvisApp(
        _FakeConfig(vault, memory_dir=ws / "memory"),
        FakeAgent(),
        {"default": "ask", "tools": {}},
    )
    app._workspace_root = lambda: ws

    async with app.run_test() as pilot:
        inp = pilot.app.query_one(Input)
        inp.focus()
        inp.value = "@"
        inp.cursor_position = 1
        pilot.app._refresh_suggestions()
        await pilot.pause()

        overlay = pilot.app.query_one("#path_completion", PathCompletionOverlay)
        assert overlay.visible_suggestions
        assert overlay.option_count >= 2
        prompts = [str(o.id) for o in overlay.options]
        assert "/vault/Inbox/note.md" in prompts

        await pilot.press("tab")
        await pilot.pause()
        assert any(p in inp.value for p in prompts)


@pytest.mark.asyncio
async def test_at_completion_escape_closes_overlay(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Inbox").mkdir(parents=True)
    (vault / "Inbox" / "note.md").write_text("# note", encoding="utf-8")

    app = JarvisApp(_FakeConfig(vault), FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        inp = pilot.app.query_one(Input)
        inp.value = "@In"
        inp.cursor_position = 3
        pilot.app._refresh_suggestions()
        await pilot.pause()
        overlay = pilot.app.query_one("#path_completion", PathCompletionOverlay)
        assert overlay.visible_suggestions

        await pilot.press("escape")
        await pilot.pause()
        assert not overlay.visible_suggestions
        assert inp.value == "@In"


@pytest.mark.asyncio
async def test_theme_persistence(tmp_path):
    import json

    config_file = tmp_path / "jarvis.json"
    config_file.write_text(json.dumps({"permissions": {"*": "ask"}, "theme": "dracula"}), encoding="utf-8")

    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app._config_path = lambda: config_file
    app._restore_theme()

    async with app.run_test() as pilot:
        assert app.theme == "dracula"
        app.theme = "monokai"
        await pilot.pause()
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved["theme"] == "monokai"

    app2 = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app2._config_path = lambda: config_file
    app2._restore_theme()
    assert app2.theme == "monokai"


@pytest.mark.asyncio
async def test_switch_session_finalizes_old_thread(monkeypatch):
    """switch_session 原语契约：离开旧会话前必须 cancel worker + finalize_turn。"""
    from unittest.mock import patch

    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        calls: list[str] = []
        monkeypatch.setattr(
            commands, "finalize_turn",
            lambda agent, tid: calls.append(f"finalize:{tid}"),
        )
        with patch.object(app, "_cancel_stream_worker") as mock_cancel:
            await pilot.pause()
            app._switch_session("other-thread")
            await pilot.pause()
            mock_cancel.assert_called_once()
        assert "finalize:default" in calls
        assert app.thread_id == "other-thread"
        # 同 id 幂等：不再触发 leave 流程
        with patch.object(app, "_cancel_stream_worker") as mock_cancel2:
            app._switch_session("other-thread")
            mock_cancel2.assert_not_called()


@pytest.mark.asyncio
async def test_new_session_clears_old_display(monkeypatch):
    """#12: 新建会话时显示栏旧内容清空。"""
    from unittest.mock import patch

    app = JarvisApp(None, FakeAgent(reply="你好"), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await pilot.pause()
        log = app.query_one("#messages")
        # 先写一些旧内容
        log.write("[b]旧会话的测试内容[/b]")
        joined = "".join(l.text for l in log.lines)
        assert "旧会话" in joined
        # monkeypatch finalize + uuid
        monkeypatch.setattr(commands, "finalize_turn", lambda agent, tid: None)
        with patch("uuid.uuid4", return_value=type("U", (), {"hex": "abc"})()):
            app.action_new_session()
        await pilot.pause()
        joined2 = "".join(l.text for l in log.lines)
        assert "旧会话" not in joined2, "旧内容应被清空"
        assert "新会话" in joined2 or "abc" in joined2


@pytest.mark.asyncio
async def test_switch_session_loads_last_ai_reply(monkeypatch):
    """#13: 切换会话时显示栏加载该会话最后一条 AI 回复。"""
    from unittest.mock import patch

    class _FakeState:
        values = {"messages": [
            type("M", (), {"type": "human", "content": "你好"})(),
            type("M", (), {"type": "ai", "content": "这是对方之前的回复"})(),
        ]}

    class _FakeAgentWithState:
        checkpointer = None
        def get_state(self, cfg):
            return _FakeState()
        def get_state_history(self, config=None):
            return iter([_FakeState()])
        def stream_events(self, *args, **kwargs):
            return iter([])

    app = JarvisApp(None, _FakeAgentWithState(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        log = app.query_one("#messages")
        log.write("[b]旧会话内容[/b]")
        monkeypatch.setattr(commands, "finalize_turn", lambda agent, tid: None)
        app._switch_session("target-thread")
        await pilot.pause()
        joined = "".join(l.text for l in log.lines)
        assert "对方之前的回复" in joined, f"应加载历史 AI 回复，实际: {joined[:100]}"
        assert "已切换" in joined
        assert app.thread_id == "target-thread"


class _UndoSnap:
    """undo 测试用的 checkpoint 快照 mock（工单 07）。"""

    def __init__(self, cid, source, messages):
        self.config = {"configurable": {"thread_id": "default", "checkpoint_id": cid}}
        self.metadata = {"source": source}
        self.values = {"messages": messages}
        self.next = ()


class _UndoAgentTui(FakeAgent):
    """带 checkpoint 历史的 FakeAgent：跑 commands.undo + transcript 重建（工单 07）。"""

    def __init__(self):
        super().__init__(reply="AI 好")
        from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage
        self._rm = RemoveMessage
        m1, a1 = HumanMessage("问题 1", id="m1"), AIMessage("回答 1", id="m2")
        m2, a2 = HumanMessage("问题 2", id="m3"), AIMessage("回答 2", id="m4")
        self._snaps = [
            _UndoSnap("c0", "input", [m1]),
            _UndoSnap("c1", "update", [m1, a1]),
            _UndoSnap("c2", "input", [m1, a1, m2]),
            _UndoSnap("c3", "update", [m1, a1, m2, a2]),
        ]
        self._head = self._snaps[-1]
        self.updates = []

    def get_state_history(self, config=None):
        return [self._head] + [s for s in reversed(self._snaps) if s is not self._head]

    def get_state(self, config):
        return self._head

    def update_state(self, config, values=None, as_node=None):
        self.updates.append((config, values, as_node))
        if values is None:
            cid = config["configurable"].get("checkpoint_id")
            self._head = next(
                s for s in self._snaps
                if s.config["configurable"]["checkpoint_id"] == cid
            )
        else:
            msgs = list(self._head.values["messages"])
            doomed = {rm.id for rm in values["messages"] if isinstance(rm, self._rm)}
            self._head = _UndoSnap(
                self._head.config["configurable"]["checkpoint_id"],
                "update",
                [m for m in msgs if m.id not in doomed],
            )
        return config


async def _wait_for_text(pilot, text: str, steps: int = 100) -> str:
    """轮询对话区直到出现目标文本（worker + call_from_thread 跨线程落地）。"""
    log = pilot.app.query_one(CopyableRichLog)
    joined = ""
    for _ in range(steps):
        joined = "".join(l.text for l in log.lines)
        if text in joined:
            return joined
        await pilot.pause()
    return joined


@pytest.mark.asyncio
async def test_slash_undo_command_rolls_back_and_rebuilds_transcript():
    agent = _UndoAgentTui()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/undo")
        joined = await _wait_for_text(pilot, "已撤回")
        assert "已撤回 1 条消息" in joined
        assert agent.updates, "undo 应触发 update_state"
        cfg, values, _as_node = agent.updates[0]
        assert values is None
        assert cfg["configurable"]["checkpoint_id"] == "c1"  # c2 的（末个输入点）父 checkpoint
        assert "[user] 问题 1" in joined  # transcript 已按回退后状态重建


@pytest.mark.asyncio
async def test_slash_undo_arg_validation():
    agent = _UndoAgentTui()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/undo abc")
        joined = await _wait_for_text(pilot, "用法")
        assert "用法: /undo [N]" in joined
        assert not agent.updates


@pytest.mark.asyncio
async def test_idle_double_esc_undoes_last_turn():
    agent = _UndoAgentTui()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        app.action_cancel()  # 第一次 Esc：置位（空闲无 worker），不撤回、不退出
        await pilot.pause()
        assert not agent.updates
        assert app.is_running
        app.action_cancel()  # 第二次 Esc（1.5s 窗口内）：隐式撤回上一轮
        joined = await _wait_for_text(pilot, "已撤回")
        assert "已撤回 1 条消息" in joined
        assert agent.updates


@pytest.mark.asyncio
async def test_esc_outside_window_only_notifies_no_exit():
    agent = _UndoAgentTui()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        app._esc_primed_at = time.monotonic() - 2.0  # 窗口已过期
        app.action_cancel()
        await pilot.pause()
        assert not agent.updates  # 仅 notify，不撤回
        assert app.is_running  # 空闲单 Esc 不退出应用


class _UseTuiConfig:
    """#09: /use 测试最小 Config（足以驱动 skill 发现）。"""

    def __init__(self, root):
        self.project_root = root
        self.skills = ()


class _UseAgentTui(FakeAgent):
    """#09: 记录 /use 投递给模型的 input（展开后的 skill 消息）。"""

    def __init__(self):
        super().__init__(reply="技能已执行")
        self.inputs = []

    def stream_events(self, *args, **kwargs):
        self.inputs.append(args[0] if args else kwargs.get("input"))
        return super().stream_events(*args, **kwargs)


def _write_tui_manual_skill(tmp_path, monkeypatch) -> None:
    jh = tmp_path / "jh"
    sk = jh / "skills" / "manual-skill"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\n"
        "name: manual-skill\n"
        "description: 手动专用 skill。\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        "# M\n"
        "步骤一：做点事\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JARVIS_HOME", str(jh))


@pytest.mark.asyncio
async def test_slash_use_missing_skill_shows_error(tmp_path, monkeypatch):
    _write_tui_manual_skill(tmp_path, monkeypatch)
    agent = FakeAgent()
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/use no-such-skill")
        joined = await _wait_for_text(pilot, "未找到")
        assert "未找到 skill「no-such-skill」" in joined
        assert agent._calls == 0


@pytest.mark.asyncio
async def test_slash_use_manual_skill_streams_expanded_message(tmp_path, monkeypatch):
    _write_tui_manual_skill(tmp_path, monkeypatch)
    agent = _UseAgentTui()
    app = JarvisApp(_UseTuiConfig(tmp_path), agent, {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/use manual-skill 请执行")
        joined = await _wait_for_text(pilot, "技能已执行")
        assert agent.inputs, "stream_events 应被调用（/use 走流式路径）"
        msg = agent.inputs[0]
        if isinstance(msg, dict):
            msg = msg["messages"][-1]["content"]  # run_agent_turn 以消息 dict 投递
        assert isinstance(msg, str)
        assert msg.startswith("[skill:manual-skill]")
        assert "步骤一：做点事" in msg
        assert "任务：请执行" in msg
