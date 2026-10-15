"""Modal 布局规约 + PrefixModal 测试（工单 01/02/04）。

规约（tui.py 各 Modal 共同遵守）：
- 内容容器 width:80%; height:auto; max-height:70%
- 可滚动 body overflow-y:auto
- 按钮行固定在模态底部（ModalScreen 尾部 yield → 短屏也永远可见）
"""

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Button, Input, OptionList, Static

from src.commands import ToolInvocation
from src.tui import (
    CopyPickerModal,
    EditParamsModal,
    PermissionModal,
    PunctPanelModal,
    PrefixModal,
    modal_edit_result,
)


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


def _start(size=(80, 24)):
    host = _ModalHost()
    return host


def test_modal_edit_result_pure() -> None:
    assert modal_edit_result({"a": 1, "b": "x"}, {"a": "  ", "b": "y"}) == {"a": 1, "b": "y"}
    assert modal_edit_result({}, {}) == {}


@pytest.mark.asyncio
async def _mount_and_check(modal, checker, size=(80, 24)) -> None:
    host = _start()
    cm = host.run_test(size=size)
    pilot = await cm.__aenter__()
    try:
        host.push_screen(modal)
        await pilot.pause()
        await checker(host, pilot)
    finally:
        host.exit()
        await pilot.pause()
        await cm.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_permission_modal_buttons_visible_at_24_rows() -> None:
    async def check(host, pilot) -> None:
        for bid in ("btn_approve", "btn_always", "btn_reject", "btn_edit"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 被遮住了（24 行短屏）"

    await _mount_and_check(PermissionModal(_inv()), check)


@pytest.mark.asyncio
async def test_permission_modal_long_preview_keeps_buttons() -> None:
    """preview 内容超过 12 行 → 截断滚动，按钮行仍在 24 行屏内可见。"""
    long_cmd = (
        "powershell -Command Get-ChildItem -Recurse D:\\ | Select-Object "
        "FullName, Length, LastWriteTime | Sort-Object | Format-Table -AutoSize | Out-String -Width 300"
    )

    async def check(host, pilot) -> None:
        for bid in ("btn_approve", "btn_always", "btn_reject", "btn_edit"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 被长 preview 推出屏幕"

    await _mount_and_check(PermissionModal(_inv("execute", long_cmd, {"command": long_cmd})), check)


@pytest.mark.asyncio
async def test_edit_params_modal_many_keys_buttons_visible() -> None:
    args = {f"k{i:02d}": f"v{i}" for i in range(12)}

    async def check(host, pilot) -> None:
        for bid in ("btn_ok", "btn_cancel"):
            btn = host.screen.query_one(f"#{bid}", Button)
            assert btn.visible, f"{bid} 在多参数时不可见（24 行短屏）"

    await _mount_and_check(EditParamsModal(args), check)


@pytest.mark.asyncio
async def test_copy_picker_visible_at_24_rows() -> None:
    async def check(host, pilot) -> None:
        assert host.screen.query_one("#copy_list", OptionList).visible

    await _mount_and_check(CopyPickerModal(_HostApp()), check)


@pytest.mark.asyncio
async def test_punct_panel_visible_at_24_rows() -> None:
    async def check(host, pilot) -> None:
        assert host.screen.query_one("#punct_list", OptionList).visible

    await _mount_and_check(PunctPanelModal(_HostApp()), check)


@pytest.mark.asyncio
async def test_prefix_modal_layout_and_input() -> None:
    async def check(host, pilot) -> None:
        inp = host.screen.query_one("#prefix_input", Input)
        assert inp.value == "git"
        assert host.screen.query_one("#btn_prefix_ok", Button).visible
        assert host.screen.query_one("#btn_prefix_cancel", Button).visible
        inp.value = "npm"

    await _mount_and_check(PrefixModal("git"), check)


@pytest.mark.asyncio
async def test_permission_modal_s_opens_prefix_modal_for_execute() -> None:
    """execute 按 s → PrefixModal；Esc 取消回审批；文件工具 s → 直接完成。"""
    host = _start()
    cm = host.run_test(size=(80, 24))
    pilot = await cm.__aenter__()
    try:
        host.push_screen(PermissionModal(_inv("execute", "git log --oneline", {"command": "git log --oneline"})))
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(host.screen, PrefixModal), "execute 应按 s 弹 PrefixModal"
        # 取消（Esc）→ 回到审批 Modal
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(host.screen, PermissionModal)

        host.screen.dismiss()
        await pilot.pause()
        host.push_screen(PermissionModal(_inv("write_file", "/tmp/x.py", {"file_path": "/tmp/x.py"})))
        await pilot.pause()
        await pilot.press("s")
        await pilot.pause()
        assert not isinstance(host.screen, PermissionModal), "文件工具 s 应直接完成（无二级 Modal）"
    finally:
        host.exit()
        await pilot.pause()
        await cm.__aexit__(None, None, None)
