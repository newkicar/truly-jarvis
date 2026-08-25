"""#08 Plan/Act 模式：middleware 拦截 + system 注入 + TUI 切换。"""
import pytest

from langchain_core.messages import AIMessage, SystemMessage

from src.plan_mode import (
    PLAN_TOOLS,
    PlanModeMiddleware,
    current_mode,
    set_mode,
)


def _req(tool_call=None):
    from types import SimpleNamespace

    return SimpleNamespace(tool_call=tool_call or {})


def _handler_marker(marker):
    def handler(request):
        marker.append("called")
        return "ok"

    return handler


class _Req:
    """wrap_model_call 的最小 request：system_message + override。"""

    def __init__(self, system_text="base"):
        self.system_message = SystemMessage(content=system_text)
        self.messages = []

    def override(self, *, system_message):
        self.system_message = system_message
        return self


def test_default_mode_is_act():
    state = {}
    assert current_mode(state) == "act"


def test_set_mode_toggles():
    state = {}
    set_mode(state, "plan")
    assert current_mode(state) == "plan"
    set_mode(state, "act")
    assert current_mode(state) == "act"


def test_act_mode_does_not_block_writes():
    state = {}
    mw = PlanModeMiddleware(state)
    marker: list = []
    res = mw.wrap_tool_call(_req({"name": "write_file", "id": "c1"}), _handler_marker(marker))
    assert res == "ok" and marker == ["called"]


def test_plan_mode_blocks_write_tools():
    state = {}
    set_mode(state, "plan")
    mw = PlanModeMiddleware(state)
    for tool in PLAN_TOOLS:
        res = mw.wrap_tool_call(_req({"name": tool, "id": "c1"}), lambda r: "should-not-run")
        assert getattr(res, "status", "") == "error", tool
        assert "Plan" in str(res.content)


def test_plan_mode_blocks_execute_no_hitl_popup():
    """2026-08-25 回归：Plan 下 execute 必须硬拦（否则穿透到 HITL 弹窗）。"""
    state = {}
    set_mode(state, "plan")
    mw = PlanModeMiddleware(state)
    res = mw.wrap_tool_call(
        _req({"name": "execute", "id": "c1", "args": {"command": "echo hi"}}),
        lambda r: "PASSED-TO-HITL",
    )
    assert getattr(res, "status", "") == "error"
    assert "Plan" in str(res.content)


def test_plan_mode_allows_read_tools():
    state = {}
    set_mode(state, "plan")
    mw = PlanModeMiddleware(state)
    marker: list = []
    for tool in ("read_file", "ls", "grep", "glob"):
        res = mw.wrap_tool_call(_req({"name": tool, "id": "c1"}), _handler_marker(marker))
        assert res == "ok", tool
    assert len(marker) == 4


@pytest.mark.asyncio
async def test_plan_mode_async_block():
    state = {}
    set_mode(state, "plan")
    mw = PlanModeMiddleware(state)
    res = await mw.awrap_tool_call(
        _req({"name": "write_file", "id": "c1"}), lambda r: "no"
    )
    assert getattr(res, "status", "") == "error"


def test_plan_mode_injects_system_prompt():
    state = {}
    set_mode(state, "plan")
    mw = PlanModeMiddleware(state)
    req = _Req("base prompt")
    out = mw.wrap_model_call(req, lambda r: r.system_message.content)
    assert "base prompt" in out and "Plan" in out


def test_act_mode_no_injection():
    state = {}
    mw = PlanModeMiddleware(state)
    req = _Req("base prompt")
    out = mw.wrap_model_call(req, lambda r: r.system_message.content)
    assert out == "base prompt"


# ---- TUI 切换 ----

from tests.test_tui import FakeAgent


@pytest.mark.asyncio
async def test_tab_toggles_mode_and_ui():
    from textual.widgets import Static

    from src.tui import JarvisApp

    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        frame = app.query_one("#editor_frame")
        await pilot.press("tab")
        await pilot.pause()
        assert current_mode(app.permission_state) == "plan"
        assert "-plan" in frame.classes
        assert "Plan" in app.sub_title
        await pilot.press("tab")
        await pilot.pause()
        assert current_mode(app.permission_state) == "act"
        assert "-plan" not in frame.classes
        await pilot.press("shift+tab")
        await pilot.pause()
        assert current_mode(app.permission_state) == "plan"


@pytest.mark.asyncio
async def test_completion_active_tab_still_accepts():
    from unittest.mock import patch

    from src.tui import JarvisApp

    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        # 构造补全活跃状态：Tab 应走接受建议，不切模式
        app._completion_active = True

        class _Overlay:
            def hide(self):
                pass

        app._path_completion_overlay = lambda: _Overlay()
        with patch.object(app, "action_accept_suggestion") as mock_accept:
            await pilot.press("tab")
            mock_accept.assert_called_once()
        assert current_mode(app.permission_state) == "act"


@pytest.mark.asyncio
async def test_ai_header_carries_mode():
    state = {}
    set_mode(state, "plan")
    from src.tui_format import ai_message_header_markup

    header = ai_message_header_markup(mode=current_mode(state))
    assert "[Plan]" in header
    header_act = ai_message_header_markup(mode="act")
    assert "[Act]" in header_act


@pytest.mark.asyncio
async def test_prompt_marker_shows_mode_label():
    from textual.widgets import Static

    from src.tui import JarvisApp

    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        marker = app.query_one("#prompt", Static)
        # 默认 act：普通提示符
        assert "-plan" not in marker.classes
        await pilot.press("tab")
        await pilot.pause()
        assert "-plan" in marker.classes
        assert "PLAN" in str(marker.render())
        await pilot.press("tab")
        await pilot.pause()
        assert "-plan" not in marker.classes
        assert "PLAN" not in str(marker.render())
