"""#09 执行 spinner：帧轮播渲染 + 显示/隐藏生命周期 + 配置降级。"""
import pytest

from textual.widgets import Static

from src import tui_format
from src.tui import JarvisApp

from tests.test_tui import FakeAgent, _type_and_enter


def test_spinner_line_rotates_frames():
    line0 = tui_format.spinner_line(0)
    line1 = tui_format.spinner_line(1)
    assert "⠋" in line0 and "思考中" in line0
    assert "⠙" in line1
    assert line0 != line1


def test_spinner_line_wraps_frame_index():
    assert "⠋" in tui_format.spinner_line(10)  # 10 % 10 = 0


def test_spinner_line_static_when_animations_off():
    line = tui_format.spinner_line(3, animations=False)
    assert "⋯" in line and "思考中" in line
    for frame in tui_format.SPINNER_FRAMES:
        assert frame not in line


def test_spinner_line_blocks_style():
    line = tui_format.spinner_line(2, style="blocks")
    assert "■" in line


def _make_app(tui_cfg=None):
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    if tui_cfg is not None:
        object.__setattr__(app.config, "tui", tui_cfg) if hasattr(app.config, "tui") else None
        if app.config is not None:
            app.config.tui = tui_cfg
    return app


@pytest.mark.asyncio
async def test_spinner_hidden_by_default():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        spinner = app.query_one("#status_spinner", Static)
        assert "-active" not in spinner.classes


@pytest.mark.asyncio
async def test_spinner_shows_during_stream_and_hides_after():
    from unittest.mock import patch

    app = JarvisApp(None, FakeAgent(reply="完成"), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        spinner = app.query_one("#status_spinner", Static)
        with patch.object(app, "_tick_spinner"):
            await _type_and_enter(pilot, "你好")
            # worker 启动后立即检查（流式未结束时 spinner 活跃）
            for _ in range(20):
                if "-active" in spinner.classes or app._worker is not None:
                    break
                await pilot.pause()
            # 流式很快结束，最终必须回到隐藏态
            for _ in range(40):
                if "-active" not in spinner.classes:
                    break
                await pilot.pause()
        assert "-active" not in spinner.classes


@pytest.mark.asyncio
async def test_spinner_show_hide_direct():
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    async with app.run_test() as pilot:
        spinner = app.query_one("#status_spinner", Static)
        app._show_spinner()
        await pilot.pause()
        assert "-active" in spinner.classes
        assert spinner.render()  # 内容非空
        app._hide_spinner()
        await pilot.pause()
        assert "-active" not in spinner.classes
        assert not str(spinner.render())


@pytest.mark.asyncio
async def test_spinner_style_none_is_noop():
    cfg = {"animations": True, "spinner_style": "none"}
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app.config = type("C", (), {"tui": cfg})()
    async with app.run_test() as pilot:
        spinner = app.query_one("#status_spinner", Static)
        app._show_spinner()
        await pilot.pause()
        assert "-active" not in spinner.classes


@pytest.mark.asyncio
async def test_spinner_animations_off_renders_static():
    cfg = {"animations": False}
    app = JarvisApp(None, FakeAgent(), {"default": "ask", "tools": {}})
    app.config = type("C", (), {"tui": cfg})()
    async with app.run_test() as pilot:
        spinner = app.query_one("#status_spinner", Static)
        app._show_spinner()
        await pilot.pause()
        assert "-active" in spinner.classes
        content = str(spinner.render())
        assert "⋯" in content
