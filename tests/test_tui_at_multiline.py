"""Bug 1（@ 补全在框内换行后的续行不弹提示框）试点红灯：分层定位。

自建目录纪律：不用 tmp_path（本机 pytest 基 temp 目录 WinError 5 中毒）。
分层：
- A 纯函数层：text/cursor 直接置位 + _refresh_suggestions
- B 事件层：pilot 真实按键（first → shift+enter → @），并记录
  JarvisTextChanged 是否到达 app（区分「事件没到」与「到了但状态不对」）。
"""
import os
import shutil
import uuid
from pathlib import Path

import pytest

from src.tui import JarvisApp, JarvisTextArea, PathCompletionOverlay
from tests.test_tui import _FakeConfig, FakeAgent

TEST_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".scratch", "tui-at-multiline-tmp",
)


def _mk_fixture():
    root = os.path.join(TEST_ROOT, uuid.uuid4().hex[:10])
    ws = os.path.join(root, "project")
    vault = os.path.join(root, "vault")
    memory = os.path.join(root, "memory")
    os.makedirs(os.path.join(ws, "src"))
    open(os.path.join(ws, "main.py"), "w").write("x = 1\n")
    open(os.path.join(ws, "src", "util.py"), "w").write("y = 2\n")
    os.makedirs(os.path.join(vault, "Inbox"))
    open(os.path.join(vault, "Inbox", "note.md"), "w").write("# note\n")
    os.makedirs(memory)
    return root, Path(ws), Path(vault), Path(memory)


def _cleanup(root):
    shutil.rmtree(root, ignore_errors=True)


def _make_app(ws, vault, memory):
    cfg = _FakeConfig(vault, memory_dir=memory)
    cfg.project_root = ws  # Path：_workspace_root()/virtual_path_mappings 需要；Header sub_title 用 .name
    app = JarvisApp(cfg, FakeAgent(), {"default": "ask", "tools": {}})
    return app


@pytest.mark.asyncio
async def test_at_line1_control():
    """对照组：第一行 @ 应弹提示框（既有行为回归护栏）。"""
    root, ws, vault, memory = _mk_fixture()
    try:
        app = _make_app(ws, vault, memory)
        async with app.run_test() as pilot:
            inp = pilot.app.query_one("#input", JarvisTextArea)
            inp.focus()
            inp.text = "@"
            inp.cursor_location = (0, 1)
            pilot.app._refresh_suggestions()
            await pilot.pause()
            overlay = pilot.app.query_one("#path_completion", PathCompletionOverlay)
            assert overlay.visible_suggestions, "第一行 @ 应有候选（护栏）"
    finally:
        _cleanup(root)


@pytest.mark.asyncio
async def test_at_line2_pure_refresh():
    """A 层：text='first\\n@' cursor=(1,1) 直接置位 → _refresh_suggestions。"""
    root, ws, vault, memory = _mk_fixture()
    try:
        app = _make_app(ws, vault, memory)
        async with app.run_test() as pilot:
            inp = pilot.app.query_one("#input", JarvisTextArea)
            inp.focus()
            inp.text = "first\n@"
            inp.cursor_location = (1, 1)
            pilot.app._refresh_suggestions()
            await pilot.pause()
            overlay = pilot.app.query_one("#path_completion", PathCompletionOverlay)
            assert overlay.visible_suggestions, "A 层：续行 @ 应弹提示框"
    finally:
        _cleanup(root)


@pytest.mark.asyncio
async def test_at_line2_keypress_flow():
    """B 层：真实按键 first → shift+enter → @，走 on_event 事件链；
    记录 JarvisTextChanged 到达情况以定位断点。"""
    root, ws, vault, memory = _mk_fixture()
    try:
        app = _make_app(ws, vault, memory)
        async with app.run_test() as pilot:
            inp = pilot.app.query_one("#input", JarvisTextArea)

            seen_changed = []
            orig_handler = pilot.app.on_jarvis_text_changed

            def spy_handler(event):
                seen_changed.append((event.widget.id, inp.text, inp.cursor_location))
                orig_handler(event)

            pilot.app.on_jarvis_text_changed = spy_handler

            inp.focus()
            await pilot.press("f", "i", "r", "s", "t")
            await pilot.press("shift+enter")
            await pilot.press("at")
            await pilot.pause()
            assert "\n" in inp.text, (
                f"B 层前置：换行应生效，实际 text={inp.text!r} cursor={inp.cursor_location}"
            )
            overlay = pilot.app.query_one("#path_completion", PathCompletionOverlay)
            assert overlay.visible_suggestions, (
                "B 层：续行 @ 应弹提示框（text=%r cursor=%s overlay_state=%s changed_events=%s）"
                % (inp.text, inp.cursor_location, pilot.app._overlay_state, seen_changed)
            )
    finally:
        _cleanup(root)
