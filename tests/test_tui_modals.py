"""Modal 布局规约 + PrefixModal 测试（工单 01/02/04）。

规约（tui.py 各 Modal 共同遵守）：
- 内容容器 width:80%; height:auto; max-height:70%
- 可滚动 body overflow-y:auto
- 按钮行固定在模态底部（ModalScreen 尾部 yield → 短屏也永远可见）
"""

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Label, OptionList, Static

from src.commands import ToolInvocation
from src.tui import (
    CopyPickerModal,
    EditParamsModal,
    ModalTextArea,
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


def test_modal_edit_result_multiline_preserved() -> None:
    """tui-ux10：多行值原样保留（尾换行不 strip）。"""
    assert modal_edit_result({"command": "old"}, {"command": "ls\npwd\n"}) == {"command": "ls\npwd\n"}


def test_modal_edit_result_all_whitespace_falls_back() -> None:
    """全空白（含多行空白）→ 回落原值。"""
    assert modal_edit_result({"command": "git log"}, {"command": "  \n "}) == {"command": "git log"}


def test_modal_edit_result_missing_key_falls_back() -> None:
    """values 缺 key → 回落原值。"""
    assert modal_edit_result({"command": "git log"}, {}) == {"command": "git log"}


def test_modal_edit_result_short_value_untouched() -> None:
    """非空白值：原样使用（不做 strip）。"""
    assert modal_edit_result({"command": "git status"}, {"command": "npm ci"}) == {"command": "npm ci"}


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
async def test_edit_params_modal_showline_and_prefill() -> None:
    """tui-ux10：每参数 = 原文只读展示行（Label）+ 多行编辑框（ModalTextArea 预填原值）；
    标题带工具名，path 行展示目标。"""

    async def check(host, pilot) -> None:
        ta = host.screen.query_one("#param_0", ModalTextArea)
        assert ta.text == "whoami", f"未预填原值：{ta.text!r}"
        show = host.screen.query_one(".param_show", Label)
        assert "command = whoami" in show.content, f"展示行缺原文：{show.content!r}"
        assert host.screen.query_one("#edit_title", Label).content == "编辑参数 · execute"
        assert host.screen.query_one("#edit_path", Label).content == "目标: git log"

    await _mount_and_check(
        EditParamsModal({"command": "whoami"}, tool_name="execute", path="git log"), check
    )


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
        inp = host.screen.query_one("#prefix_input", Input)
        assert pilot.app.focused is inp, f"PrefixModal 打开应聚焦 #prefix_input（got {pilot.app.focused!r}）"
        assert inp.select_on_focus is False, "前缀框须 select_on_focus=False（消灰选）"
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

def _buttons_within(host, ids: tuple[str, ...], screen_h: int) -> None:
    """断言按钮 region 完整落在 screen_h 行屏内。

    不能用 ``btn.visible``——Textual 的 visible 只查 style.visible 标志，
    不查 region 是否越出屏幕（短屏下被裁的按钮 visible 仍为 True）。
    """
    for bid in ids:
        btn = host.screen.query_one(f"#{bid}", Button)
        r = btn.region
        assert r.y >= 0 and r.y + r.height <= screen_h, f"{bid} region={r} 超出 {screen_h} 行屏"


def _long_exec_inv() -> ToolInvocation:
    """31 行 execute 命令：审批窗口内容远超 12 行短屏。"""
    cmd = "\n".join(f"echo line-{i:02d}" for i in range(31))
    return ToolInvocation(name="execute", path=cmd, args={"command": cmd})


@pytest.mark.asyncio
async def test_permission_modal_short_screen_12_buttons_on_screen() -> None:
    """12 行屏 + 31 行命令：四按钮必须完整可见（按钮行固定位置，不随内容下移出屏）。"""

    async def check(host, pilot) -> None:
        _buttons_within(host, ("btn_approve", "btn_always", "btn_reject", "btn_edit"), 12)

    await _mount_and_check(PermissionModal(_long_exec_inv()), check, size=(80, 12))


@pytest.mark.asyncio
async def test_permission_modal_preview_scrollable_on_short_screen() -> None:
    """内容容器可滚动：#perm_box 是 VerticalScroll；长 preview 自身 max_scroll_y > 0。"""
    from textual.containers import VerticalScroll

    async def check(host, pilot) -> None:
        box = host.screen.query_one("#perm_box")
        assert isinstance(box, VerticalScroll), "#perm_box 应为 VerticalScroll（内容超出时可滚动）"
        preview = host.screen.query_one("#perm_preview")
        assert preview.max_scroll_y > 0, "长内容下 preview 应可内部滚动（max_scroll_y>0）"

    await _mount_and_check(PermissionModal(_long_exec_inv()), check, size=(80, 12))


@pytest.mark.asyncio
async def test_edit_params_modal_short_screen_12_buttons_on_screen() -> None:
    """12 行屏 + 12 参数：确认/取消按钮必须完整可见。"""
    args = {f"k{i:02d}": f"v{i}" for i in range(12)}

    async def check(host, pilot) -> None:
        _buttons_within(host, ("btn_ok", "btn_cancel"), 12)

    await _mount_and_check(EditParamsModal(args), check, size=(80, 12))



UNSAFE_CMD = "python -c \"" + "cells=[" + "str(c) + '=' + str(ws.max_column)" + " for c in ws.columns]\""


@pytest.mark.asyncio
async def test_permission_modal_markup_safe_with_unsafe_args() -> None:
    """崩溃红灯（崩溃.txt）：execute 命令文本含 [ ' = 字符时，PermissionModal 的
    Label/Static 把工具参数当 Rich markup 解析 → MarkupError 崩掉 TUI 布局。
    修复后：参数/diff 按纯文本渲染，modal 正常出且原文保留。"""

    inv = _inv("execute", UNSAFE_CMD, {"command": UNSAFE_CMD})

    async def check(host, pilot) -> None:
        # Textual 8.2.8：Label 无 .renderable；render() 返回已 markup 处理的 Content
        lbl = host.screen.query_one("#perm_path")
        assert "max_column" in str(lbl.render()).strip(), (
            f"label 丢失原文: {lbl.render()!r}"
        )

    await _mount_and_check(PermissionModal(inv), check)
