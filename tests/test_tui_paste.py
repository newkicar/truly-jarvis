"""PasteTextArea 粘贴链路测试（tui-ux13 起：#input 为 JarvisTextArea，全量多行粘贴）。"""
import asyncio

import pytest

from src import tui
from src.tui import JarvisTextArea


class _FakeAgent:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return "ok"

    async def ainvoke(self, *args, **kwargs):
        return type("R", (), {"content": ""})()

    def invoke(self, *args, **kwargs):
        return type("R", (), {"content": ""})()


def _make_host():
    return tui.JarvisApp(None, _FakeAgent(), {"default": "ask", "tools": {}})


async def _wait_for_text(inp: JarvisTextArea, expected: str, tries: int = 80) -> bool:
    for _ in range(tries):
        if inp.text == expected:
            return True
        await asyncio.sleep(0.05)
    return inp.text == expected


@pytest.mark.asyncio
async def test_ctrl_v_pastes_os_clipboard(monkeypatch):
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "pasted 文本")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "pasted 文本")


@pytest.mark.asyncio
async def test_ctrl_shift_v_pastes_os_clipboard(monkeypatch):
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "shift-paste")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+shift+v")
        assert await _wait_for_text(inp, "shift-paste")


@pytest.mark.asyncio
async def test_mouse_paste_right_and_middle():
    from unittest.mock import patch

    from rich.style import Style

    from textual import events

    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        for button in (2, 3):
            event = events.MouseDown(
                widget=inp,
                x=1,
                y=0,
                delta_x=0,
                delta_y=0,
                button=button,
                shift=False,
                meta=False,
                ctrl=False,
                screen_x=1,
                screen_y=0,
                style=Style(),
            )
            with patch.object(inp, "action_paste") as mock_paste:
                await inp._on_mouse_down(event)
                mock_paste.assert_called_once()

        left_event = events.MouseDown(
            widget=inp,
            x=1,
            y=0,
            delta_x=0,
            delta_y=0,
            button=1,
            shift=False,
            meta=False,
            ctrl=False,
            screen_x=1,
            screen_y=0,
            style=Style(),
        )
        with patch.object(inp, "action_paste") as mock_paste:
            await inp._on_mouse_down(left_event)
            mock_paste.assert_not_called()


@pytest.mark.asyncio
async def test_paste_multiline_full_text(monkeypatch):
    """tui-ux13 语义 ①：全量多行粘贴（旧首行裁剪废弃）。"""
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "first\nsecond\nthird")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "first\nsecond\nthird")


def test_read_os_clipboard_smoke():
    """真实环境冒烟：不抛异常即可（内容取决于测试机剪贴板）。"""
    result = tui.read_os_clipboard()
    assert isinstance(result, str)

@pytest.mark.asyncio
async def test_image_only_clipboard_inserts_placeholder_not_stale_text(monkeypatch):
    """Bug：复制图片/截屏后粘贴仍是上轮对话文字。

    双根因之一（顺序）：图片独占剪贴板时 Get-Clipboard -Raw 恒空，
    旧链路「OS 文本空 → 先回落 app.clipboard」永远挡住 OS 图片分支。
    修复后优先级：OS 文本 → OS 图片 → app 剪贴板。"""
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "")
    monkeypatch.setattr(tui, "try_copy_clipboard_image", lambda: "C:/fake/img.png")
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        app.copy_to_clipboard("stale 对话文字")
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "[Image #1]")
        assert "[Image #1]" not in app.clipboard  # app 剪贴板未参与


@pytest.mark.asyncio
async def test_os_image_beats_app_fallback_even_with_stale_clipboard(monkeypatch):
    """回归锚点：app.clipboard 有旧文字且 OS 图片同时存在 → 图片占位胜出。"""
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "")
    calls = []
    monkeypatch.setattr(
        tui, "try_copy_clipboard_image", lambda: calls.append(1) or "C:/fake/img.png"
    )
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        app.copy_to_clipboard("stale")
        inp.focus()
        await pilot.press("ctrl+v")
        assert calls, "OS 图片分支未被触达（app 回落顺序错误）"
        assert await _wait_for_text(inp, "[Image #1]")


@pytest.mark.asyncio
async def test_no_os_content_falls_back_to_app_clipboard(monkeypatch):
    """既有语义保留：OS 文本/图片均无 → 回落 app 剪贴板（app 内复制内容）。"""
    monkeypatch.setattr(tui, "read_os_clipboard", lambda: "")
    monkeypatch.setattr(tui, "try_copy_clipboard_image", lambda: None)
    app = _make_host()
    async with app.run_test() as pilot:
        inp = app.query_one("#input", JarvisTextArea)
        app.copy_to_clipboard("app 内复制")
        inp.focus()
        await pilot.press("ctrl+v")
        assert await _wait_for_text(inp, "app 内复制")


@pytest.mark.asyncio
async def test_modal_paste_os_image_notifies_no_stale_text(monkeypatch):
    """ModalTextArea 同序：图片独占剪贴板 → 提示无法粘进参数框，
    不回落 app 剪贴板旧文字（旧行为）。"""
    from src.tui import EditParamsModal, ModalTextArea

    async def check(host, pilot) -> None:
        ta = host.screen.query_one("#param_0", ModalTextArea)
        host.copy_to_clipboard("stale")
        monkeypatch.setattr(tui, "read_os_clipboard", lambda: "")
        monkeypatch.setattr(tui, "try_copy_clipboard_image", lambda: "C:/fake/img.png")
        notes = []
        monkeypatch.setattr(host, "notify", lambda msg, **kw: notes.append(str(msg)))
        # 走真实入口 action_paste（worker 线程），call_from_thread 才合法
        ta.action_paste()
        for _ in range(100):
            await pilot.pause()
            if notes:
                break
        assert ta.text == "", f"参数框被改动：{ta.text!r}"
        assert any("图片" in n for n in notes), f"未提示图片：{notes!r}"
        assert "stale" not in ta.text

    app = _make_host()
    cm = app.run_test(size=(80, 24))
    pilot = await cm.__aenter__()
    try:
        app.push_screen(EditParamsModal({"command": ""}))
        await pilot.pause()
        await check(app, pilot)
    finally:
        app.exit()
        await pilot.pause()
        await cm.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_modal_paste_falls_back_to_app_clipboard(monkeypatch):
    """ModalTextArea：OS 文本/图片均无 → 回落 app 剪贴板（既有语义保留）。"""
    from src.tui import EditParamsModal, ModalTextArea

    async def check(host, pilot) -> None:
        ta = host.screen.query_one("#param_0", ModalTextArea)
        host.copy_to_clipboard("app 内复制")
        monkeypatch.setattr(tui, "read_os_clipboard", lambda: "")
        monkeypatch.setattr(tui, "try_copy_clipboard_image", lambda: None)
        # 走真实入口 action_paste（worker 线程），call_from_thread 才合法
        ta.action_paste()
        for _ in range(100):
            await pilot.pause()
            if ta.text == "app 内复制":
                break
        assert ta.text == "app 内复制", f"回落未生效：{ta.text!r}"

    app = _make_host()
    cm = app.run_test(size=(80, 24))
    pilot = await cm.__aenter__()
    try:
        app.push_screen(EditParamsModal({"command": ""}))
        await pilot.pause()
        await check(app, pilot)
    finally:
        app.exit()
        await pilot.pause()
        await cm.__aexit__(None, None, None)


def test_clipboard_image_windows_script_uses_winforms():
    """平台根因回归：Windows 脚本必须走 WinForms GetImage（本地实证），
    不得回退到 Get-Clipboard -Format Image（Management 7.0 无此参数）。"""
    import inspect

    import src.clipboard_image as ci

    src_text = inspect.getsource(ci.try_copy_clipboard_image)
    assert "System.Windows.Forms.Clipboard" in src_text
    # 负向断言只查执行脚本段（函数体 docstring 里的弃用说明不算）
    code_part = src_text.split("script = (", 1)[1]
    assert "Get-Clipboard -Format Image" not in code_part


def test_clipboard_image_write_contract(monkeypatch):
    """子进程契约：经 JARVIS_CLIP_FILE 环境变量落盘、文件非空才返回路径。"""
    import os
    import sys
    import tempfile

    import src.clipboard_image as ci

    if sys.platform != "win32":
        pytest.skip("Windows-only clipboard-image subprocess contract")

    target_dir = os.path.join(tempfile.gettempdir(), "jarvis-test-clip")
    os.makedirs(target_dir, exist_ok=True)
    written = []

    def fake_run(cmd, *args, **kwargs):
        env = kwargs.get("env") or {}
        out = env.get("JARVIS_CLIP_FILE")
        assert out, "目标路径必须经 JARVIS_CLIP_FILE 传入（引号安全）"
        with open(out, "wb") as f:
            f.write(b"\x89PNG fake")
        written.append(out)

        class _R:
            returncode = 0

        return _R()

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    monkeypatch.setattr(ci, "_new_temp_target", lambda: os.path.join(target_dir, "out.png"))
    path = ci.try_copy_clipboard_image()
    assert path == os.path.join(target_dir, "out.png")
    assert written
