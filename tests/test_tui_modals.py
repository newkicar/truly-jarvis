"""Modal 布局规约测试（工单 01/02）：24 行短终端下按钮行必须可见可点。

规约（tui.py 各 Modal 共同遵守）：
- 内容容器 width:80%; height:auto; max-height:70%
- 可滚动 body overflow-y:auto
- 按钮行固定在模态底部（ModalScreen 尾部 yield → 短屏也永远可见）
"""

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Button, OptionList, Static

from src.commands import ToolInvocation
from src.tui import CopyPickerModal, EditParamsModal, PermissionModal, PunctPanelModal, modal_edit_result


class _HostApp:
    """最小 host：CopyPickerModal 需要 _copy_to_clipboard；PunctPanel 需要 _insert_punctuation。"""

    def __init__(self) -> None:
        self.copied: list[str] = []
        self.inserted: list[str] = []

    def _copy_to_clipboard(self, text: str, note: str = "") -> None:
        self.copied.append(text)

    def _insert_punctuation(self, ch: str) -> None:
        self.inserted.append(ch)


class _ModalHost(App):
    """测试宿主：把 ModalScreen push 进来做短屏渲染。"""

    def compose(self) -> ComposeResult:
        yield Static("host")


def _inv(name: str = "execute", path: str = "git log", args: dict | None = None):
    return ToolInvocation(name=name, path=path, args=args or {})


def test_modal_edit_result_pure() -> None:
    assert modal_edit_result({"a": 1, "b": "x"}, {"a": "  ", "b": "y"}) == {"a": 1, "b": "y"}
    assert modal_edit_result({}, {}) == {}


async def _mount(modal, size=(80, 24)):
    """mount modal 到宿主；返回 (host, close)，close() 负责 Esc 关闭 + 收尾。"""
    host = _ModalHost()
    cm = host.run_test(size=size)
    pilot = await cm.__aenter__()
    host.push_screen(modal)
    await pilot.pause()

    async def close() -> None:
        await pilot.press("escape")
        await pilot.pause()
        host.exit()
        await pilot.pause()
        await cm.__aexit__(None, None, None)

    return host, close


@pytest.mark.asyncio
async def test_permission_modal_buttons_visible_at_24_rows() -> None:
    host, close = await _mount(PermissionModal(_inv()))
    try:
        for bid in ("btn_approve", "btn_always", "btn_reject", "btn_edit"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 被遮住了（24 行短屏）"
    finally:
        await close()


@pytest.mark.asyncio
async def test_permission_modal_long_preview_keeps_buttons() -> None:
    """preview 内容超过 12 行 → 截断滚动，按钮行仍在 24 行屏内可见。"""
    long_cmd = (
        "powershell -Command Get-ChildItem -Recurse D:\\ | Select-Object "
        "FullName, Length, LastWriteTime | Sort-Object | Format-Table -AutoSize | Out-String -Width 300"
    )
    host, close = await _mount(PermissionModal(_inv("execute", long_cmd, {"command": long_cmd})))
    try:
        for bid in ("btn_approve", "btn_always", "btn_reject", "btn_edit"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 被长 preview 推出屏幕"
    finally:
        await close()


@pytest.mark.asyncio
async def test_edit_params_modal_many_keys_buttons_visible() -> None:
    args = {f"k{i:02d}": f"v{i}" for i in range(12)}
    host, close = await _mount(EditParamsModal(args))
    try:
        for bid in ("btn_ok", "btn_cancel"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 在多参数时不可见（24 行短屏）"
    finally:
        await close()


@pytest.mark.asyncio
async def test_copy_picker_visible_at_24_rows() -> None:
    host, close = await _mount(CopyPickerModal(_HostApp()))
    try:
        assert host.screen.query_one("#copy_list", OptionList).visible
    finally:
        await close()


@pytest.mark.asyncio
async def test_punct_panel_visible_at_24_rows() -> None:
    host, close = await _mount(PunctPanelModal(_HostApp()))
    try:
        assert host.screen.query_one("#punct_list", OptionList).visible
    finally:
        await close()
