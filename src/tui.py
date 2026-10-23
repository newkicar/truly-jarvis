"""Textual TUI 界面（对标 opencode 终端界面）。"""
import asyncio
import sys
from collections import defaultdict
from functools import partial
from pathlib import Path
from rich.markup import escape
from time import monotonic
from typing import ClassVar
from textual import events
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, RichLog, Static, TextArea
from textual.css.query import NoMatches
from textual.widgets.option_list import Option
from textual.worker import Worker

from src import commands, ime_shim
from src.clipboard_image import (
    build_multimodal_content,
    image_fallback_text,
    looks_like_image_path,
    try_copy_clipboard_image,
)
from src.tui_punct import ime_hint_line, is_conhost_like
from src.skill_discovery import discover_skill_catalog
from src.tui_completion import OverlayState, apply_suggestion_on_line, line_projection, resolve_overlay_state
from src.tui_log import CopyableRichLog
from src import tui_format
from src.tui_turn import TurnPresenter
from src.tui_format import (
    DEFAULT_TUI_THEME,
    LEGACY_BAD_THEMES,
    ai_message_header_markup,
    ai_stream_renderable,
    format_todos_panel,
    permission_preview,
    render_markdown,
    system_message_markup,
    user_message_markup,
)


# 空闲双 Esc 撤回窗口（秒）：窗口内第二次 Esc 触发上一轮消息层撤回（工单 07）。
ESC_UNDO_WINDOW = 1.5


def read_os_clipboard() -> str:
    """读 OS 剪贴板文本。

    终端协议不提供读通道（Textual 的 app.clipboard 只含 app 内复制的内容），
    Windows 走 PowerShell Get-Clipboard（UTF-8 输出防 GBK 乱码）；
    macOS/Linux 尽力而为。失败返回空串，不抛异常。
    """
    import subprocess

    if sys.platform == "win32":
        try:
            result = subprocess.run(  # noqa: S603
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
            return (result.stdout or "").rstrip("\r\n")
        except Exception:  # noqa: BLE001
            return ""
    for cmd in (["pbpaste"], ["wl-paste", "--no-newline"], ["xclip", "-selection", "clipboard", "-o"]):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)  # noqa: S603
            if result.returncode == 0 and result.stdout:
                return result.stdout.rstrip("\r\n")
        except Exception:  # noqa: BLE001
            continue
    return ""


class JarvisSubmitted(Message):
    """tui-ux13：主输入框提交消息（裸 Enter，多行）。text = 框内全文。"""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class JarvisTextChanged(Message):
    """tui-ux13：主输入框内容变化（补全面板刷新）；widget = 触发变化的 TextArea。"""

    def __init__(self, widget) -> None:
        self.widget = widget
        super().__init__()


class PasteTextArea(TextArea):
    """支持系统剪贴板粘贴的 TextArea（tui-ux13：旧粘贴链路整体上提为基类）。

    三个粘贴入口各自的病因与对策：
    - ctrl+v：Textual 原生 action_paste 只读 app.clipboard（仅 app 内复制内容），
      外部复制永远粘不进 → worker 读 OS 剪贴板，空则回落 app.clipboard；
    - ctrl+shift+v：终端若把它当普通按键透传，Textual 无此绑定 → 显式补绑定；
    - 右键/中键：Textual 鼠标捕获使终端级右键粘贴失效 → 绑定鼠标键触发粘贴
      （button 2/3，不碰左键选区）。
    写回走 _replace_via_keyboard + move_cursor（尊重选区；全量多行粘贴，
    旧首行裁剪语义废弃——tui-ux13 语义变化点 ①）。
    """

    BINDINGS = [
        Binding("ctrl+shift+v", "paste", "粘贴", show=False),
    ]

    def action_paste(self) -> None:
        self.run_worker(self._read_clipboard_worker, thread=True, exclusive=True)

    def _read_clipboard_worker(self) -> None:
        text = read_os_clipboard()
        if not text:
            # OS 剪贴板无文本 → 回落 app 剪贴板（app 内复制的内容）
            text = self.app.clipboard or ""
        if text:
            image_path = looks_like_image_path(text)
            if image_path:
                idx = self.app.call_from_thread(self.app._register_image_attachment, image_path)
                if idx is not None:
                    self.app.call_from_thread(self._apply_paste, f"[Image #{idx}]")
                    self.app.call_from_thread(self.app.notify, f"已插入 [Image #{idx}]")
                return
            self.app.call_from_thread(self._apply_paste, text)
            return
        image = try_copy_clipboard_image()
        if image:
            idx = self.app.call_from_thread(self.app._register_image_attachment, image)
            if idx is not None:
                self.app.call_from_thread(self._apply_paste, f"[Image #{idx}]")
                self.app.call_from_thread(self.app.notify, f"已插入 [Image #{idx}]")

    def _apply_paste(self, text: str) -> None:
        if not text or not self.is_mounted:
            return
        result = self._replace_via_keyboard(text, *self.selection)
        if result:
            self.move_cursor(result.end_location)
            self.post_message(JarvisTextChanged(self))

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button in (2, 3):
            event.stop()
            event.prevent_default()
            self.action_paste()
            return
        await super()._on_mouse_down(event)

    async def on_event(self, event: events.Event) -> None:
        """Key 事件走 on_event → 绑定链 → 私有 _on_key（Textual 8.x 实证）。

        在 on_event 层对「产生文本变化的键」补 post JarvisTextChanged：仅
        「可见字符」（ord>=32 且非 127）与 backspace/delete 视为文本变化。
        注意：escape（\x1b）等控制键 character 非空但不改文本，若 post 会重触发
        _refresh_suggestions、把用户刚用 escape 关闭的补全面板重新弹出（tui-ux13 回归）。
        绑定链消费的键（shift+enter/ctrl+j 换行）由 action_newline 自行 post，不重复。
        """
        if isinstance(event, events.Key):
            await super().on_event(event)
            char = event.character
            if (
                (char and ord(char) >= 32 and ord(char) != 127)
                or event.key in ("backspace", "delete")
            ):
                self.post_message(JarvisTextChanged(self))
            return
        await super().on_event(event)


class JarvisTextArea(PasteTextArea):
    """tui-ux13 主输入框：框内多行（shift+enter/ctrl+j 插 \\n）、裸 Enter 提交、
    Tab（补全不活跃时）切换 Plan/Act。模态内子类（ModalTextArea）不继承提交拦截。"""

    BINDINGS = [
        *PasteTextArea.BINDINGS,
        # #08 Plan/Act：输入框聚焦时 Tab 切换模式（widget 级绑定先于 Screen 的
        # focus_next；补全活跃时由 app.on_key 先行拦截，仍为接受建议）。
        Binding("tab", "app.toggle_mode", "Plan/Act", show=False),
        Binding("shift+tab", "app.toggle_mode_reverse", "Plan/Act 反向", show=False),
        # tui-ux13：Shift+Enter 框内换行；Ctrl+J 为常绑退路
        #（ConPTY 对 shift 修饰键透传不保证，ctrl+j 退路在案）。
        Binding("shift+enter", "newline", "换行", show=False),
        Binding("ctrl+j", "newline", "换行(退路)", show=False),
    ]

    def action_newline(self) -> None:
        result = self._replace_via_keyboard("\n", *self.selection)
        if result:
            self.move_cursor(result.end_location)
            self.post_message(JarvisTextChanged(self))

    async def on_event(self, event: events.Event) -> None:
        # Textual 8.x：Key.key 为合成串（"enter" / "shift+enter" / "ctrl+j"），
        # 8.2.8 无 Key.modifiers 属性——裸 Enter 即 key == "enter"（shift 版 key 名不同）。
        if isinstance(event, events.Key) and event.key == "enter":
            # 裸 Enter 提交（shift+enter 的 key 名为 "shift+enter"，不在此拦截，放行给绑定链）
            event.stop()
            event.prevent_default()
            self.post_message(JarvisSubmitted(self.text))
            return
        await super().on_event(event)


class PermissionModal(ModalScreen):
    """HITL 审批覆盖层（对标 opencode permission dialog）。

    四按钮：放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)。
    dismiss 结果: dict{"decision": "approve"|"reject"|"always_approve"|"edit",
    "message": str?, "edited": {name, args}?}；"cancel" 表示放弃本轮。
    """
    # tui-ux8：默认焦点落在「放行」（Screen.AUTO_FOCUS 覆盖 App 的 "*"，
    # 否则 Modal 激活时焦点落 DOM 首个可聚焦部件 #perm_box，Enter 无绑定）
    AUTO_FOCUS: ClassVar[str] = "#btn_approve"

    BINDINGS = [
        Binding("a", "choose('approve')", "放行", show=False),
        Binding("s", "always", "永久放行", show=False),
        Binding("d", "choose('reject')", "拒绝", show=False),
        Binding("e", "edit_params", "编辑参数", show=False),
        Binding("escape", "choose('cancel')", "放弃", show=False),
    ]

    CSS = """
    PermissionModal {
        align: center middle;
        background: $surface;
    }
    #perm_box {
        width: 80%;
        height: auto;
        max-height: 60%;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }
    #perm_tool {
        color: $accent;
        text-style: bold;
    }
    #perm_path {
        color: $text-muted;
    }
    #perm_preview {
        height: auto;
        max-height: 14;
        overflow-y: auto;
        border: round $surface;
        background: $surface;
        margin: 1 0;
        padding: 0 1;
    }
    #perm_buttons {
        height: auto;
        width: 80%;
        margin-top: 1;
        align-horizontal: center;
    }
    """

    def __init__(self, inv: commands.ToolInvocation, *, vault_path: Path | None = None, workspace_root: Path | None = None):
        super().__init__()
        self.inv = inv
        self.vault_path = vault_path
        self.workspace_root = workspace_root
        self.path_label = "Command:" if inv.name == "execute" else "Path:"

    def compose(self) -> ComposeResult:
        # 崩溃.txt 根因：工具参数/diff 是不可信文本，Label/Static 默认 markup=True
        # 会把含 [ ' = 的命令/ diff 当 Rich markup 解析（MarkupError / 静默截断）。
        with VerticalScroll(id="perm_box", can_focus=False):
            yield Label(f"Tool: {self.inv.name}", id="perm_tool", markup=False)
            yield Label(f"{self.path_label} {self.inv.path}", id="perm_path", markup=False)
            preview = permission_preview(
                self.inv,
                vault_path=self.vault_path,
                workspace_root=self.workspace_root,
            )
            yield Static(preview, id="perm_preview", markup=False)
        with Horizontal(id="perm_buttons"):
            yield Button("放行", id="btn_approve", variant="success")
            yield Button("永久放行", id="btn_always", variant="primary")
            yield Button("拒绝", id="btn_reject", variant="error")
            yield Button("编辑参数", id="btn_edit", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_approve":
            self.dismiss({"decision": "approve"})
        elif event.button.id == "btn_always":
            self.action_always()
        elif event.button.id == "btn_reject":
            self.dismiss({"decision": "reject"})
        elif event.button.id == "btn_edit":
            self.action_edit_params()

    def action_edit_params(self) -> None:
        def got_edited(result) -> None:
            if result is not None:
                self.dismiss({"decision": "edit", "edited": result})

        self.app.push_screen(
            EditParamsModal(
                self.inv.args,
                tool_name=self.inv.name,
                path=self.inv.path,
            ),
            got_edited,
        )

    def action_choose(self, decision: str) -> None:
        self.dismiss({"decision": decision})

    def action_always(self) -> None:
        """永久放行：execute → PrefixModal（工单 04，前缀可编辑）；文件工具 → 原整工具流程。"""
        from src.permissions import extract_command_prefix
        from src.tool_call import command

        if self.inv.name != "execute":
            self.dismiss({"decision": "always_approve"})
            return
        default = extract_command_prefix(command(self.inv.args or {}))

        def got(prefix) -> None:
            if not prefix:
                return  # 取消：留在审批 Modal
            self.dismiss({"decision": "always_approve", "prefix": prefix})

        self.app.push_screen(PrefixModal(default), got)


class PrefixModal(ModalScreen):
    """execute 永久放行前缀确认（工单 04）：预填提取出的命令前缀，可编辑。

    确认后 dismiss(prefix 字符串)；取消/Esc dismiss(None) → 调用方留在审批 Modal。
    布局遵循 Modal 规约（工单 01）。
    """

    BINDINGS = [Binding("escape", "cancel", "取消")]

    AUTO_FOCUS: ClassVar[str] = "#prefix_input"

    CSS = """
    PrefixModal {
        align: center middle;
        background: $surface;
    }
    #prefix_box {
        width: 80%;
        height: auto;
        max-height: 60%;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }
    #prefix_title {
        color: $accent;
        text-style: bold;
    }
    #prefix_hint {
        color: $text-muted;
    }
    #prefix_input {
        width: 100%;
        height: 2;
        margin: 1 0;
    }
    #prefix_buttons {
        height: auto;
        width: 80%;
        margin-top: 1;
        align-horizontal: center;
    }
    """

    def __init__(self, default_prefix: str):
        super().__init__()
        self.default_prefix = default_prefix or "*"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="prefix_box", can_focus=False):
            yield Label("永久放行（按命令前缀）", id="prefix_title")
            yield Label(f'将写回 jarvis.json: "{self.default_prefix} *": allow', id="prefix_hint")
            yield Input(self.default_prefix, id="prefix_input", select_on_focus=False)
        with Horizontal(id="prefix_buttons"):
            yield Button("确认", id="btn_prefix_ok", variant="primary")
            yield Button("取消", id="btn_prefix_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_prefix_cancel":
            self.dismiss(None)
            return
        val = self.query_one("#prefix_input", Input).value.strip()
        self.dismiss(val or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


def modal_edit_result(args: dict, values: dict) -> dict:
    """纯函数：把编辑框当前值折成「确认」结果。

    tui-ux10：全空白（含多行空白）→ 回落原值；非空白 → 原样使用
    （不 strip，保留多行尾换行）。旧「.strip() or 原值」是其子集。
    """
    out: dict = {}
    for k in args:
        text = str(values.get(k, ""))
        out[k] = text if text.strip() else args[k]
    return out


def _param_display(v, limit: int = 500) -> str:
    """参数原文的只读展示：超长截断 + 尾注（「看得见改」的展示行）。"""
    s = str(v)
    if len(s) > limit:
        return s[:limit] + f"…（截断，共 {len(s)} 字符）"
    return s


class ModalTextArea(PasteTextArea):
    """模态内多行参数编辑框（tui-ux10）：结构消解 Input 的灰选态。

    Input select_on_focus=True 默认聚焦即全文选中（灰选区）+ 首键整值
    替换（用户「点就变灰、打字不显示」症状的统一根因）；TextArea 无
    select_on_focus——点击聚焦 = 光标就位、无选区（F7 显式全选）；
    原生 Enter 插 \n（多行通道）。theme 参数省略（8.2.8 仅 5 个内置
    主题，"text" 会抛 ThemeDoesNotExist）。

    tui-ux10 工单 02：OS 剪贴板粘贴通道——Textual 原生 action_paste 只读
    app.clipboard（app 内复制内容）；终端协议下外部复制的文本永远粘不进
    （同主输入框病灶）。覆盖 action_paste：worker 线程先读 OS 剪贴板
    （3s 超时不冻 UI），空则回落 app.clipboard；写回走与原生粘贴同路
    _replace_via_keyboard + move_cursor（尊重选区、读只读态自守）。
    """

    def action_paste(self) -> None:
        self.run_worker(self._paste_from_os, thread=True, exclusive=True)

    def _paste_from_os(self) -> None:
        text = read_os_clipboard()
        if not text:
            # OS 剪贴板无文本 → 回落 app 剪贴板（app 内复制的内容）
            text = self.app.clipboard or ""
        if text:
            self.app.call_from_thread(self._apply_paste, text)

class EditParamsModal(ModalScreen):
    """编辑工具参数（从权限审批进入）：逐 key 两行——原文只读展示（Label）+
    多行编辑框（ModalTextArea）；空白留空回落原值。

    布局遵循 Modal 规约（工单 01）：内容容器 80%/max 60% + 按钮行固定模态
    底部（modal_screen 尾部 → 永远可见）。tui-ux10：灰选态结构消解
    （TextArea 无 select_on_focus，点击聚焦 = 光标就位）；多行值可编辑
    （原生 Enter 插 \n）；id 索引化 `#param_{idx}`（key 含 `.`/`-` 做 CSS
    id 即坏选择器）。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        # ctrl+shift+enter 屏级退路（工单 02）：焦点编辑框插换行（原生
        # enter 为主通道，ConPTY shift 透传不保证）
        Binding("ctrl+shift+enter", "newline", "换行(退路)", show=False),
    ]

    CSS = """
    EditParamsModal {
        align: center middle;
        background: $surface;
    }
    #edit_box {
        width: 80%;
        height: auto;
        max-height: 60%;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }
    #edit_title {
        color: $accent;
        text-style: bold;
    }
    #edit_path {
        color: $text-muted;
    }
    #edit_box > .param_show {
        margin: 1 0 0 0;
    }
    #edit_box > .param_edit {
        height: 5;
        margin: 0 0 1 0;
    }
    #edit_buttons {
        height: auto;
        width: 80%;
        margin-top: 1;
        align-horizontal: center;
    }
    """

    def __init__(self, args: dict, *, tool_name: str | None = None, path: str | None = None):
        super().__init__()
        self.args = dict(args or {})
        self.tool_name = tool_name
        self.path = path
        # 索引化 id：key 不做 CSS id（key 可能含 `.`/`-` 等坏选择器字符）
        self._key_idx = {k: i for i, k in enumerate(self.args)}
        # tui-ux8 同族病灶：显式默认聚焦首个编辑框；空 args 回落 #btn_ok。
        self.AUTO_FOCUS = "#param_0" if self.args else "#btn_ok"

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="edit_box", can_focus=False):
            if self.tool_name:
                yield Label(f"编辑参数 · {self.tool_name}", id="edit_title", markup=False)
            else:
                yield Label("编辑参数（留空使用原值）", id="edit_title")
            if self.path:
                yield Label(f"目标: {self.path}", id="edit_path", markup=False)
            for k, v in self.args.items():
                # 看得见改：Label 行展示原文（超长截断 + 尾注）
                yield Label(f"{k} = {_param_display(v)}", classes="param_show", markup=False)
                yield ModalTextArea(
                    str(v),
                    placeholder=k,
                    id=f"param_{self._key_idx[k]}",
                    classes="param_edit",
                )
        with Horizontal(id="edit_buttons"):
            yield Button("确认", id="btn_ok", variant="primary")
            yield Button("取消", id="btn_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
            return
        values = {
            k: self.query_one(f"#param_{self._key_idx[k]}", ModalTextArea).text
            for k in self.args
        }
        self.dismiss(modal_edit_result(self.args, values))

    def action_cancel(self) -> None:
        self.dismiss(None)


    def action_newline(self) -> None:
        """ctrl+shift+enter 屏级退路（工单 02）：焦点编辑框插入 \n。

        TextArea 原生 enter 是多行主通道；ConPTY shift 修饰键透传不保证
        （与主输入框 Ctrl+J 退路键同款理由）。"""
        focused = self.app.focused
        if isinstance(focused, ModalTextArea):
            focused.insert("\n")


class CopyPickerModal(ModalScreen):
    """复制内容选择器（#01）：最近 AI 回复 / 最近代码块 / 整段会话。

    Enter 确认复制（走 app 的级联剪贴板写入），Esc 关闭。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
    ]

    DEFAULT_CSS = """
    CopyPickerModal {
        align: center middle;
        background: $surface;
    }

    #copy_picker {
        width: 52;
        height: auto;
        border: thick $primary;
        background: $panel;
        padding: 1 2;
    }

    #copy_picker_title {
        color: $accent;
        text-style: bold;
    }

    #copy_list {
        height: 6;
        border: round $surface;
        background: $surface;
    }
    """

    def __init__(self, app: "JarvisApp") -> None:
        super().__init__()
        self._app = app

    def compose(self) -> ComposeResult:
        with Static(id="copy_picker"):
            yield Label("复制到剪贴板（↑↓ 选择，Enter 确认）", id="copy_picker_title")
            yield OptionList(id="copy_list")

    def on_mount(self) -> None:
        listing = self.query_one("#copy_list", OptionList)
        listing.add_options(
            [
                Option("最近 AI 回复", id="ai"),
                Option("最近代码块", id="code"),
                Option("整段会话", id="session"),
            ]
        )
        listing.highlighted = 0
        listing.focus()

    def action_cancel(self) -> None:
        """Esc 关闭（Textual 8.x 已移除 Screen.cancel 内置动作，需自行定义）。"""
        self.dismiss()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        text = self._pick_text(str(event.option.id))
        self.dismiss()
        if text.strip():
            self._app._copy_to_clipboard(text, "已复制到剪贴板")
        else:
            self._app.notify("没有可复制的内容", timeout=2)

    def _pick_text(self, kind: str) -> str:
        agent = self._app.agent
        if agent is None:
            return ""
        thread_id = self._app.thread_id
        if kind == "ai":
            return commands.last_ai_text(agent, thread_id, limit=100000)
        if kind == "code":
            return commands.last_code_block(
                commands.last_ai_text(agent, thread_id, limit=100000)
            )
        if kind == "session":
            return commands.render_session_text(agent, thread_id)
        return ""


class PathCompletionOverlay(OptionList):
    """@ / 触发的建议列表（overlay，不抢输入焦点）。"""

    DEFAULT_CSS = """
    PathCompletionOverlay {
        layer: overlay;
        display: none;
        dock: bottom;
        width: 1fr;
        height: auto;
        max-height: 12;
        margin: 0 2 4 2;
        border: round $primary;
        background: $panel;
    }

    PathCompletionOverlay.-visible {
        display: block;
    }
    """

    def show_suggestions(self, items: list[tuple[str, str]]) -> None:
        """items: (label, hint)"""
        self.clear_options()
        if not items:
            self.remove_class("-visible")
            return
        for label, hint in items:
            text = f"{label}  [dim]{hint}[/dim]" if hint else label
            self.add_option(Option(text, id=label))
        self.highlighted = 0
        self.add_class("-visible")

    def hide(self) -> None:
        self.remove_class("-visible")
        self.clear_options()

    @property
    def visible_suggestions(self) -> bool:
        return self.has_class("-visible") and self.option_count > 0

    def selected_insert(self) -> str | None:
        if not self.visible_suggestions:
            return None
        option = self.get_option_at_index(self.highlighted)
        if option is None:
            return None
        return str(option.id) if option.id else str(option.prompt)


class SessionSidebar(OptionList):
    """可折叠会话列表侧边栏。聚焦后 Y 复制 ID、D 删除（由 JarvisApp 处理）。"""

    can_focus = True

    DEFAULT_CSS = """
    SessionSidebar {
        width: 22;
        min-width: 18;
        max-width: 28;
        height: 1fr;
        border-right: solid $primary;
        background: $surface;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }

    SessionSidebar.-collapsed {
        display: none;
        width: 0;
        min-width: 0;
        max-width: 0;
        padding: 0;
        border: none;
    }
    """

    def refresh_sessions(self, agent, current: str) -> None:
        threads = commands.session_thread_ids(agent)
        if current and current not in threads:
            threads = [current, *threads]
        self.clear_options()
        for thread_id in threads:
            label_text = commands.session_label(agent, thread_id)
            label = f"▸ {label_text}" if thread_id == current else label_text
            self.add_option(Option(label, id=thread_id))
        if threads:
            try:
                self.highlighted = threads.index(current)
            except ValueError:
                self.highlighted = 0


class JarvisApp(App):
    """JARVIS TUI。侧边栏 Y/Ctrl+Insert 复制会话 ID；Ctrl+C/Q 退出。"""

    ALLOW_SELECT = True

    BINDINGS = [
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+b", "toggle_sidebar", "侧边栏"),
        Binding("ctrl+t", "change_theme", "切换主题"),
        Binding("y", "copy_session_or_selection", "复制ID", show=False),
        Binding("d", "delete_highlighted_session", "删会话", show=False),
        Binding("ctrl+insert", "copy_session_or_selection", "复制", priority=True),
        Binding("ctrl+shift+c", "copy_session_or_selection", "复制", priority=True),
        Binding("ctrl+shift+y", "copy_picker", "复制内容", show=False),
        Binding("tab", "accept_suggestion", "接受建议", show=False),
        Binding("escape", "cancel", "取消", show=False),
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+c", "quit", "退出", priority=True),
    ]

    CSS = """
    Screen {
        background: $background;
    }

    .screen--selection {
        background: $primary 40%;
        color: $text;
    }

    Header {
        background: $surface;
        border-bottom: solid $primary;
    }

    Footer {
        background: $surface;
        /* height:1 的 Footer 加 border-top 会把快捷键挤到屏幕外 */
        height: 2;
        border-top: solid $primary;
    }

    #main_row {
        height: 1fr;
        min-height: 0;
        margin: 0;
    }

    #content_column {
        height: 1fr;
        min-height: 0;
        width: 1fr;
    }

    #chat_frame {
        height: 1fr;
        margin: 0 1 0 0;
        border: round $primary;
        background: $surface;
        padding: 0 1;
    }

    #chat_stack {
        height: 100%;
    }

    #messages {
        height: 1fr;
        width: 100%;
        background: transparent;
        border: none;
        padding: 0;
        scrollbar-size-vertical: 1;
        scrollbar-background: $surface;
        scrollbar-color: $primary 40%;
    }

    #ai_stream {
        height: auto;
        max-height: 50%;
        display: none;
        overflow-y: auto;
        scrollbar-size-vertical: 1;
        padding: 0 0 1 0;
        border-top: solid $primary 20%;
    }

    #ai_stream.-active {
        display: block;
    }

    #editor_frame {
        height: auto;
        margin: 1 1 1 0;
        border: round $primary;
        background: $panel;
        padding: 0 1;
    }

    #todo_panel {
        height: auto;
        max-height: 8;
        display: none;
        margin: 0 1 0 0;
        padding: 0 1;
        border: round $primary 30%;
        background: $panel 40%;
        overflow-y: auto;
    }

    #todo_panel.-active {
        display: block;
    }

    #status_spinner {
        height: 1;
        display: none;
        margin: 0 1 0 2;
        color: $warning;
    }

    #status_spinner.-active {
        display: block;
    }

    #editor_frame:focus-within {
        border: round $accent;
    }

    #editor_frame {
        transition: border 160ms;
    }

    #editor_frame.-plan,
    #editor_frame.-plan:focus-within {
        border: round $success;
    }

    #prompt {
        width: auto;
        min-width: 2;
        color: $accent;
        content-align: center middle;
    }

    #prompt.-plan {
        color: $success;
    }

    #input {
        width: 1fr;
        height: auto; min-height: 1; max-height: 5; overflow-y: auto;
        border: none;
        background: transparent;
        color: $text;
        padding: 0;
    }

    #input:focus {
        border: none;
    }
    #yolo_badge {
        display: none;
        width: auto;
        height: auto;
        border: round 20% $error 80%;
        color: $error;
        text-style: bold;
        padding: 0 1;
    }
    #yolo_badge.-active {
        display: block;
    }
    """

    def __init__(
        self,
        config,
        agent,
        permission_state: dict,
        sched=None,
        thread_id: str = "default",
        mcp_tool_count: int = 0,
        startup_lines: list[str] | None = None,
        startup_prompt: str | None = None,
    ):
        super().__init__()
        self.config = config
        self.agent = agent
        self.permission_state = permission_state
        self.sched = sched
        self.thread_id = thread_id
        self._mcp_tool_count = mcp_tool_count
        self._startup_lines = startup_lines or []
        self._startup_prompt = startup_prompt
        self._worker: Worker | None = None
        self._hitl_generation = 0
        self._resolved_hitl: dict[str, set[str]] = defaultdict(set)
        self._pending_hitl_keys: set[str] = set()
        self._completion_active = False
        self._overlay_state = OverlayState(kind="none", at_index=0, items=())
        self._sidebar_visible = True
        self._spinner_timer = None
        self._spinner_frame = 0
        self._image_seq = 0  # #03: 剪贴板图片附件序号（[Image #N]）
        self._image_attachments: dict[int, str] = {}  # #03: 占位符号 → 临时图片文件
        self._esc_primed_at = 0.0  # 空闲双 Esc 撤回窗口计时（monotonic；工单 07）
        self._ime_drift_notified = False  # tui-ux13 L1: IME 漂移一次性 notify 标记
        self._turn_gate_threads: set[str] = set()  # tui-ux7 #02: 回合门（执行/收尾中的 thread 集合）
        self._queued_messages: list[tuple[str, str]] = []  # tui-ux7 #02: FIFO 排队（(thread_id, raw text)
        self.title = "JARVIS"
        self._restore_theme()
        self._update_sub_title()

    def _config_path(self) -> Path:
        if self.config and getattr(self.config, "project_root", None):
            return self.config.project_root / "jarvis.json"
        return commands.project_root() / "jarvis.json"

    def _restore_theme(self) -> None:
        try:
            import json

            path = self._config_path()
            data = json.loads(path.read_text(encoding="utf-8"))
            saved = data.get("theme")
            if saved in LEGACY_BAD_THEMES or (
                sys.platform == "win32" and saved and saved.startswith("ansi")
            ):
                saved = DEFAULT_TUI_THEME
                data["theme"] = saved
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if saved and saved in self.available_themes:
                self.theme = saved
            elif DEFAULT_TUI_THEME in self.available_themes:
                self.theme = DEFAULT_TUI_THEME
        except Exception:
            if DEFAULT_TUI_THEME in self.available_themes:
                self.theme = DEFAULT_TUI_THEME

    def watch_theme(self, theme_name: str) -> None:
        try:
            import json

            path = self._config_path()
            data = json.loads(path.read_text(encoding="utf-8"))
            data["theme"] = theme_name
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    def _update_sub_title(self) -> None:
        from src.plan_mode import current_mode
        from src.permissions import yolo_active

        parts = [self.thread_id]
        if self._mcp_tool_count:
            parts.append(f"MCP:{self._mcp_tool_count}")
        if self.config and getattr(self.config, "project_root", None):
            parts.append(str(self.config.project_root.name))
        parts.append(current_mode(self.permission_state).capitalize())
        if self.sched is not None:
            try:
                n = len(self.sched.get_jobs())
                parts.append(f"sched:{n}")
            except Exception:
                pass
        if yolo_active(self.permission_state, self.thread_id):
            parts.append("[YOLO]")
        self.sub_title = "  ".join(parts)
        self._refresh_yolo_badge()

    def _refresh_yolo_badge(self) -> None:
        """tui-ux14: YOLO 徽章（输入框最右），随 _update_sub_title 联动显示。"""
        try:
            badge = self.query_one("#yolo_badge", Static)
        except (NoMatches, ScreenStackError):
            return  # tui-ux7: app 收尾/拆屏后节点可能已移除；
            # tui-ux14: __init__ 期（DOM 未挂载）query_one 发 ScreenStackError，同样 no-op
        from src.permissions import yolo_active

        if yolo_active(self.permission_state, self.thread_id):
            badge.add_class("-active")
            badge.update("YOLO Mode")  # tui-ux14: 纯文本继承 CSS $error/bold（真彩 hex 在终端不渲染）
        else:
            badge.remove_class("-active")
            badge.update("")

    def _vault_path(self) -> Path | None:
        return getattr(self.config, "vault_path", None) if self.config else None

    def _workspace_root(self) -> Path | None:
        if not self.config:
            return None
        return getattr(self.config, "project_root", None)

    def _copy_on_select(self) -> bool:
        if not self.config:
            return False
        tui = getattr(self.config, "tui", None) or {}
        return bool(tui.get("copy_on_select", True))

    def _at_reference_style(self) -> str:
        """#04: @ 引用呈现方式（virtual/dual/real，缺省 dual）。"""
        if not self.config:
            return "dual"
        tui = getattr(self.config, "tui", None) or {}
        style = tui.get("at_reference_style", "dual")
        return style if style in ("virtual", "dual", "real") else "dual"

    def _register_image_attachment(self, path: str) -> int:
        """#03: 登记一个剪贴板/路径图片附件，返回占位符序号。"""
        self._image_seq += 1
        self._image_attachments[self._image_seq] = path
        return self._image_seq

    def _clear_image_attachments(self) -> None:
        self._image_attachments.clear()
        self._image_seq = 0

    def _image_input_mode(self) -> str:
        """#03: model.image_input 能力门（auto/on/off，未配置回落 auto）。"""
        if not self.config:
            return "auto"
        mode = getattr(self.config, "model_image_input", "auto")
        return mode if mode in ("auto", "on", "off") else "auto"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main_row"):
            yield SessionSidebar(id="session_sidebar")
            with Vertical(id="content_column"):
                with Container(id="chat_frame"):
                    with Vertical(id="chat_stack"):
                        yield CopyableRichLog(
                            id="messages",
                            wrap=True,
                            markup=True,
                            auto_scroll=True,
                            copy_on_select=self._copy_on_select(),
                        )
                        yield Static("", id="ai_stream")
                yield Static("", id="todo_panel")
                with Horizontal(id="editor_frame"):
                    yield Static("›", id="prompt")
                    yield JarvisTextArea(
                        placeholder="输入消息，/ 开头为命令，@ 引用路径",
                        id="input",
                        show_line_numbers=False,
                    )
                    yield Static("", id="yolo_badge", markup=False)  # tui-ux14: 内容纯文本，禁 markup 解析（防回归）
                yield Static("", id="status_spinner")
        yield PathCompletionOverlay(id="path_completion")
        yield Footer()

    def _write_system(self, log: RichLog, text: str) -> None:
        log.write(system_message_markup(text))

    def _write_ai(self, log: RichLog, text: str) -> None:
        log.write(ai_message_header_markup())
        log.write(render_markdown(text))
        log.write("")

    def _show_ai_stream(self) -> None:
        try:
            self.query_one("#messages", CopyableRichLog).clear_user_selection()
        except Exception:
            pass
        try:
            stream = self.query_one("#ai_stream", Static)
        except NoMatches:
            return  # tui-ux7: app 收尾/拆屏后节点已移除（worker 排空期 call_from_thread 兜底）
        stream.add_class("-active")

    def _hide_ai_stream(self) -> None:
        try:
            stream = self.query_one("#ai_stream", Static)
        except NoMatches:
            return  # tui-ux7: app 收尾/拆屏后节点已移除（worker 排空期 call_from_thread 兜底）
        stream.remove_class("-active")
        stream.update("")

    def _spinner_config(self) -> tuple[bool, str]:
        """(animations, style)；config 缺失时默认开动画、braille。"""
        tui = getattr(self.config, "tui", None) or {}
        return bool(tui.get("animations", True)), str(tui.get("spinner_style", "braille"))

    def _show_spinner(self) -> None:
        animations, style = self._spinner_config()
        if style == "none":
            return
        spinner = self.query_one("#status_spinner", Static)
        if not animations:
            spinner.update(tui_format.spinner_line(0, animations=False))
            spinner.add_class("-active")
            return
        self._spinner_frame = 0
        spinner.update(tui_format.spinner_line(0, style=style))
        spinner.add_class("-active")
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _tick_spinner(self) -> None:
        _, style = self._spinner_config()
        try:
            spinner = self.query_one("#status_spinner", Static)
        except Exception:
            return
        if "-active" not in spinner.classes:
            return
        self._spinner_frame += 1
        spinner.update(tui_format.spinner_line(self._spinner_frame, style=style))

    def _hide_spinner(self) -> None:
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        try:
            spinner = self.query_one("#status_spinner", Static)
        except NoMatches:
            return  # tui-ux7: app 收尾/拆屏后节点已移除（worker 排空期 call_from_thread 兜底）
        spinner.remove_class("-active")
        spinner.update("")

    def _show_cancel_banner(self) -> None:
        """tui-ux7 #01: Esc 取消 → spinner 立即固定为「已取消」banner（收尾结束由 presenter finally 的 _hide_spinner 自动清空）。"""
        if self._spinner_config()[1] == "none":
            return
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        spinner = self.query_one("#status_spinner", Static)
        spinner.add_class("-active")
        spinner.update("[dim]已取消，正在收尾（当前步骤结束后停止）[/dim]")

    def _release_turn_gate(self, tid: str) -> None:
        """tui-ux7 #02: 释放 tid 的回合门并重投排队队首（UI 线程；由 worker 终结经 call_from_thread 回调）。

        会话已切走（tid != 当前）→ 旧会话排队消息作废 + 提示；否则弹出 tid 队首重入
        _handle_user_message（重入时门已空 → 获取门并启动下一轮，FIFO 保守）。
        """
        self._turn_gate_threads.discard(tid)
        if tid != self.thread_id:
            stale = [item for item in self._queued_messages if item[0] == tid]
            if stale:
                self._queued_messages = [item for item in self._queued_messages if item[0] != tid]
                self.notify(f"会话 {tid} 有 {len(stale)} 条排队消息因会话切换未发送", timeout=3)
            return
        idx = next((i for i, (t, _x) in enumerate(self._queued_messages) if t == tid), None)
        if idx is None:
            return
        _t, raw = self._queued_messages.pop(idx)
        self._handle_user_message(raw)

    def _update_ai_stream(self, text: str) -> None:
        try:
            stream = self.query_one("#ai_stream", Static)
        except NoMatches:
            return  # tui-ux7: app 收尾/拆屏后节点已移除（worker 排空期 call_from_thread 兜底）
        stream.update(ai_stream_renderable(text))

    def _finalize_ai_stream(self, log: RichLog, text: str, mode: str | None = None) -> None:
        self._hide_ai_stream()
        if not isinstance(text, str):
            text = commands.content_to_text(text)
        log.write(ai_message_header_markup(mode=mode))
        log.write(render_markdown(text))
        log.write("")

    def _fetch_agent_todos(self) -> list[dict]:
        try:
            state = self.agent.get_state(commands.thread_config(self.thread_id))
            values = getattr(state, "values", None) or {}
            raw = values.get("todos") or []
            return [t for t in raw if isinstance(t, dict)]
        except Exception:
            return []

    def _refresh_todos_panel(self, todos: list[dict] | None = None) -> None:
        try:
            panel = self.query_one("#todo_panel", Static)
        except NoMatches:
            return  # tui-ux7: app 收尾/拆屏后节点已移除（worker 排空期 call_from_thread 兜底）
        markup = format_todos_panel(todos if todos is not None else self._fetch_agent_todos())
        if markup:
            panel.add_class("-active")
            panel.update(markup)
        else:
            panel.remove_class("-active")
            panel.update("")

    def on_mount(self) -> None:
        log = self.query_one("#messages", RichLog)
        self._write_system(
            log, "JARVIS 就绪。@ 引用路径，/ 命令；Tab 接受建议，Enter 发送；Tab（无补全时）切换 Plan/Act。"
        )
        self._write_system(
            log,
            "会话：Ctrl+B 开侧边栏 → 点选 → Y 复制 ID / D 删除；或 /delete-session 2 按序号。"
            " 复制：对话区拖选（松开自动复制）；/copy 或 Ctrl+Shift+Y 选复制内容；Ctrl+Insert。退出：/exit 或 Ctrl+Q。",
        )
        # #02: conhost 标点提示（tui.ime_hint auto/on/off；auto 时仅 conhost 显示）
        hint = ime_hint_line(self._ime_hint_mode(), is_conhost_like())
        if hint:
            self._write_system(log, hint)
        for line in self._startup_lines:
            self._write_system(log, line)
        self._refresh_session_sidebar()
        self._maybe_warn_ime_drift()
        self.query_one("#input", JarvisTextArea).focus()
        if self._startup_prompt:
            self.call_after_refresh(self._submit_startup_prompt)

    def _submit_startup_prompt(self) -> None:
        prompt = (self._startup_prompt or "").strip()
        self._startup_prompt = None
        if prompt:
            self._handle_user_message(prompt)

    def _handle_user_message(self, raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        vpmapping = commands.virtual_path_mappings(self.config)
        # tui-ux7 #02: 回合串行化门——收尾期新消息排队而非并发启动（不清输入、不写日志，不重复）。
        # 入门类型 = 普通消息（含虚拟路径引用）+ /replay + /use + /undo；
        # 读类 slash（/exit、/help、/copy、其他命令）不入门。
        is_slash_cmd = text.startswith("/") and not commands.is_virtual_path_reference(text, vpmapping)
        turn_message = (not is_slash_cmd) or text.split()[0] in ("/replay", "/undo", "/use")
        if turn_message and self.thread_id in self._turn_gate_threads:
            queued_here = sum(1 for t, _x in self._queued_messages if t == self.thread_id)
            self._queued_messages.append((self.thread_id, text))
            self.notify(
                f"上一轮取消收尾中，已排队 {queued_here + 1} 条，收尾结束后自动发送",
                timeout=2,
            )
            return
        input_widget = self.query_one("#input", JarvisTextArea)
        input_widget.clear()
        log = self.query_one("#messages", RichLog)
        log.write(user_message_markup(text))
        # #04: 消息含虚拟前缀（/workspace/ 等）时追加 dim 锚点行，指出真实目录。
        for line in commands.path_anchor_lines(text, vpmapping):
            log.write(line)
        if text == "/exit":
            self.exit()
            return
        if text == "/help":
            log.write(commands.TUI_HELP)
            return
        if text == "/copy":
            self.action_copy_picker()
            return
        # #04: /workspace/、/vault/ 等虚拟前缀路径引用（如 @ 引用）发模型；
        # 其余 / 开头仍走命令分发（未知命令照旧报「未知命令」）。
        if text.startswith("/") and not commands.is_virtual_path_reference(text, vpmapping):
            parts = text.split()
            if parts[0] == "/replay":
                if len(parts) != 2:
                    log.write("用法: /replay <checkpoint_id>")
                    return
                err, full_id = commands.prepare_replay(self.agent, self.thread_id, parts[1])
                if err:
                    log.write(err)
                    return
                log.write(system_message_markup(f"正在重跑 checkpoint {parts[1]}…"))
                self._show_spinner()
                self._turn_gate_threads.add(self.thread_id)
                self._worker = self.run_worker(
                    partial(self._stream_agent, checkpoint_id=full_id), thread=True
                )
                return
            if parts[0] == "/undo":
                if len(parts) > 1:
                    log.write("用法: /undo（无参）；/undo 只撤回最近 1 条，多轮请反复调用")
                    return
                log.write(system_message_markup("正在撤回 1 条消息…"))
                self._show_spinner()
                self._turn_gate_threads.add(self.thread_id)
                self._worker = self.run_worker(
                    partial(self._undo_worker, 1), thread=True
                )
                return
            if parts[0] == "/use":
                # #09: 手动调用 manual-only skill → 完整指令作为本轮 user 消息投递
                msg, err = commands.expand_use_command(self.config, text)
                if err is not None:
                    log.write(err)
                    return
                log.write(f"使用 skill「{parts[1]}」…")
                self._show_spinner()
                self._turn_gate_threads.add(self.thread_id)
                self._worker = self.run_worker(
                    partial(self._stream_agent, user_input=msg), thread=True
                )
                return
            cmd = parts[0]
            log.write(system_message_markup(f"正在执行 {cmd}…"))
            self._worker = self.run_worker(partial(self._run_command_worker, text), thread=True)
            return
        stream_input: str | list = text
        image_fallback: str | None = None
        if "[Image #" in text:
            # #03: 提交时展开 [Image #N] 占位符 → 多模态 content（off 时回落纯文本路径引用）。
            mode = self._image_input_mode()
            if mode == "off":
                stream_input = image_fallback_text(text, self._image_attachments)
            else:
                stream_input = build_multimodal_content(text, self._image_attachments)
                image_fallback = image_fallback_text(text, self._image_attachments)
            self._clear_image_attachments()
        self._show_spinner()
        self._turn_gate_threads.add(self.thread_id)
        self._worker = self.run_worker(
            partial(
                self._stream_agent,
                user_input=stream_input,
                image_input=self._image_input_mode(),
                image_fallback=image_fallback,
            ),
            thread=True,
        )

    def _run_command_worker(self, text: str) -> None:
        """后台线程执行可能阻塞的命令（/history、/fork 等）。"""
        try:
            result, new_thread, _replay_cid = commands.dispatch_command(
                self.agent, self.thread_id, text, self.sched,
                permission_state=self.permission_state,
            )
        except Exception as exc:
            result, new_thread = f"命令失败: {exc}", None
        self.call_from_thread(
            self._apply_command_result, result, new_thread, self._yolo_notify_text(text)
        )

    def _yolo_notify_text(self, text: str) -> str | None:
        """tui-ux12: /yolo on/off 执行后短 banner（幂等同文案）；裸查询/非法参数不弹。"""
        parts = text.split()
        if len(parts) < 2 or parts[0] != "/yolo":
            return None
        arg = parts[1].lower()
        if arg == "on":
            return "YOLO 已开启：本会话免审批"
        if arg == "off":
            return "YOLO 已关闭：恢复原 permissions 规则"
        return None

    def _undo_worker(self, n: int) -> None:
        """后台线程跑 commands.undo（checkpoint 读写可能阻塞；工单 07）。

        撤回前先取末条用户消息全文，撤回成功后回填输入框（对标 codex/opencode）。
        """
        try:
            restored = commands.last_user_input(self.agent, self.thread_id)
        except Exception:  # noqa: BLE001
            restored = ""
        try:
            result = commands.undo(self.agent, self.thread_id, n)
        except Exception as exc:  # noqa: BLE001
            result = f"撤回失败: {exc}"
        self.call_from_thread(self._apply_undo_result, result, restored)
        self.call_from_thread(self._release_turn_gate, self.thread_id)

    def _apply_undo_result(self, result: str, restored: str = "") -> None:
        """撤回后重建对话区 transcript + 写结果横幅（工单 07）；成功时把被撤回的用户消息回填输入框。"""
        log = self.query_one("#messages", CopyableRichLog)
        log.clear()
        rendered = commands.render_session_text(self.agent, self.thread_id)
        if rendered:
            log.write(escape(rendered))  # 转义 [user]/[JARVIS] 前缀，防止被 Rich markup 吞掉
        else:
            log.write("[dim]（会话已清空）[/dim]")
        log.write(system_message_markup(result))
        self._refresh_session_sidebar()
        input_box = self.query_one("#input", JarvisTextArea)
        input_box.focus()
        if restored and result.startswith("已撤回"):
            input_box.text = restored
            input_box.cursor_location = (restored.count("\n"), len(restored.rsplit("\n", 1)[-1]))

    def _trigger_implicit_undo(self) -> None:
        """双 Esc 隐式撤回：作废本线程悬挂 HITL，然后撤回 1 条（与 /undo 1 同 worker 路径）。"""
        # tui-ux7 #02: 收尾中撤回被拒绝（不排队——撤销操作不能隔回重放）
        if self.thread_id in self._turn_gate_threads:
            self.notify("上一轮取消收尾中，请等待收尾结束后再撤回", timeout=2)
            return
        self._mark_hitl_resolved(self.thread_id, set(self._pending_hitl_keys))
        self._pending_hitl_keys.clear()
        self._bump_hitl_generation()
        log = self.query_one("#messages", RichLog)
        log.write(system_message_markup("正在撤回 1 条消息…"))
        self._show_spinner()
        self._turn_gate_threads.add(self.thread_id)
        self._worker = self.run_worker(partial(self._undo_worker, 1), thread=True)

    def _cancel_stream_worker(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    def _bump_hitl_generation(self) -> None:
        """作废进行中的 HITL Modal（切会话 / Esc / turn 未完成）。"""
        self._hitl_generation += 1
        if isinstance(self.screen, PermissionModal):
            self.screen.dismiss(None)

    def _mark_hitl_resolved(self, thread_id: str, keys: set[str]) -> None:
        if keys:
            self._resolved_hitl[thread_id].update(keys)

    def _apply_command_result(
        self,
        result: str,
        new_thread: str | None,
        yolo_notify_text: str | None = None,
    ) -> None:
        log = self.query_one("#messages", RichLog)
        log.write(result)
        if new_thread:
            # 命令驱动的轻量切换（/delete-session、/fork）：不走
            # _leave_current_thread——命令层语义已定，此处仅接管新 id。
            self._adopt_thread(new_thread, f"[b]已切换到会话 {new_thread}[/b]")
        else:
            self._refresh_session_sidebar()
        self.query_one("#input", JarvisTextArea).focus()
        if yolo_notify_text:
            # tui-ux12: /yolo 状态变更后短 banner + 副标题 [YOLO] 标记联动
            self.notify(yolo_notify_text, timeout=3)
            self._update_sub_title()

    def _session_sidebar(self) -> SessionSidebar:
        return self.query_one("#session_sidebar", SessionSidebar)

    def _refresh_session_sidebar(self) -> None:
        self._session_sidebar().refresh_sessions(self.agent, self.thread_id)

    def _leave_current_thread(self, old_thread: str) -> None:
        """离开当前会话前的固定 choreography（会话切换的唯一出口）。

        cancel 流式 worker → 记 HITL 已决 → 清 pending → bump 代数 → finalize。
        任何要更换 self.thread_id 的路径都必须先走这里。
        """
        self._cancel_stream_worker()
        self._mark_hitl_resolved(old_thread, set(self._pending_hitl_keys))
        self._pending_hitl_keys.clear()
        self._bump_hitl_generation()
        commands.finalize_turn(self.agent, old_thread)

    def _adopt_thread(self, thread_id: str, message: str, *, clear: bool = False) -> None:
        """接管新会话：换 id → 副标题 → 侧边栏 → 写入消息。clear=True 时先清空显示栏。"""
        self.thread_id = thread_id
        self._update_sub_title()
        self._refresh_session_sidebar()
        log = self.query_one("#messages", RichLog)
        if clear:
            log.clear()
        log.write(message)

    def _switch_session(self, thread_id: str) -> None:
        if not thread_id or thread_id == self.thread_id:
            return
        old_thread = self.thread_id
        self._leave_current_thread(old_thread)
        # #13: 清空 → 切换提示 → 加载历史（与 action_new_session 顺序一致）
        log = self.query_one("#messages", RichLog)
        log.clear()
        self._adopt_thread(thread_id, f"[b]已切换到会话 {thread_id}[/b]")
        pairs = commands.thread_history_text(self.agent, thread_id)
        for role, content in pairs:
            if role == "user":
                log.write(user_message_markup(content))
            else:
                self._write_ai(log, content)
        if not pairs:
            log.write("[i][dim]（暂无历史）[/dim][/i]")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "session_sidebar":
            return
        thread_id = event.option.id
        if thread_id is not None:
            self._switch_session(str(thread_id))
        self.query_one("#input", JarvisTextArea).focus()

    def action_toggle_mode(self) -> None:
        self._switch_mode(1)

    def action_toggle_mode_reverse(self) -> None:
        self._switch_mode(-1)

    def _switch_mode(self, direction: int) -> None:
        """Tab 切换 Plan/Act（补全活跃时由 on_key 拦截，不会走到这里）。"""
        from src.plan_mode import MODES, current_mode, set_mode

        idx = MODES.index(current_mode(self.permission_state))
        next_mode = MODES[(idx + direction) % len(MODES)]
        set_mode(self.permission_state, next_mode)
        self._refresh_mode_indicator()
        frame = self.query_one("#editor_frame")
        if next_mode == "plan":
            frame.add_class("-plan")
        else:
            frame.remove_class("-plan")
        self._update_sub_title()

    def _refresh_mode_indicator(self) -> None:
        """输入框左侧模式文字标记（对标 opencode prompt 的 agent 名标签）。"""
        from src.plan_mode import current_mode

        marker = self.query_one("#prompt", Static)
        if current_mode(self.permission_state) == "plan":
            marker.update("[b] PLAN [/b]")
            marker.add_class("-plan")
        else:
            marker.update("›")
            marker.remove_class("-plan")

    def action_toggle_sidebar(self) -> None:
        sidebar = self._session_sidebar()
        self._sidebar_visible = not self._sidebar_visible
        if self._sidebar_visible:
            sidebar.remove_class("-collapsed")
        else:
            sidebar.add_class("-collapsed")

    def _memories_root(self) -> Path | None:
        if not self.config:
            return None
        return getattr(self.config, "memory_dir", None)

    def _path_completion_overlay(self) -> PathCompletionOverlay:
        return self.query_one("#path_completion", PathCompletionOverlay)

    def _skills_catalog(self):
        """tui-ux9: /use skill 补全候选——逐键重扫、不缓存（新增 skill 下次按键即现）；config 缺失/异常 → None（功能关闭、不崩）。"""
        if not self.config:
            return None
        try:
            return discover_skill_catalog(self.config)
        except Exception:
            return None

    def _refresh_suggestions(self) -> None:
        inp = self.query_one("#input", JarvisTextArea)
        overlay = self._path_completion_overlay()
        line, col = line_projection(inp.text, inp.cursor_location)
        state = resolve_overlay_state(
            line,
            col,
            vault_path=self._vault_path(),
            workspace_root=self._workspace_root(),
            memories_root=self._memories_root(),
            path_mapping=commands.virtual_path_mappings(self.config),
            at_reference_style=self._at_reference_style(),
            skills=self._skills_catalog(),
        )
        self._overlay_state = state
        if not state.active:
            self._completion_active = False
            overlay.hide()
            return
        display = [(item.label, item.hint) for item in state.items]
        overlay.show_suggestions(display)
        self._completion_active = overlay.visible_suggestions

    def action_accept_suggestion(self) -> None:
        if not self._completion_active:
            return
        inp = self.query_one("#input", JarvisTextArea)
        overlay = self._path_completion_overlay()
        selected = overlay.selected_insert()
        if not selected or not self._overlay_state.active:
            return
        new_text, new_cursor = apply_suggestion_on_line(
            inp.text,
            inp.cursor_location,
            self._overlay_state.at_index,
            selected,
        )
        inp.text = new_text
        inp.cursor_location = new_cursor
        inp.focus()
        self._refresh_suggestions()

    def on_jarvis_text_changed(self, event: JarvisTextChanged) -> None:
        if event.widget.id == "input":
            self._refresh_suggestions()

    def on_key(self, event: events.Key) -> None:
        if not self._completion_active:
            return
        overlay = self._path_completion_overlay()
        if event.key == "down":
            overlay.action_cursor_down()
            event.prevent_default()
            event.stop()
        elif event.key == "up":
            overlay.action_cursor_up()
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            overlay.hide()
            self._completion_active = False
            self._overlay_state = OverlayState(kind="none", at_index=0, items=())
            event.prevent_default()
            event.stop()
        elif event.key == "tab":
            self.action_accept_suggestion()
            event.prevent_default()
            event.stop()

    def on_jarvis_submitted(self, event: JarvisSubmitted) -> None:
        """tui-ux13：主输入框提交（框内多行；尾空白/尾空行由 build_submission 裁掉）。"""
        overlay = self._path_completion_overlay()
        overlay.hide()
        self._completion_active = False
        self._overlay_state = OverlayState(kind="none", at_index=0, items=())
        vpm = commands.virtual_path_mappings(self.config)
        payload, err = commands.build_submission(event.text, tuple(vpm))
        if err:
            self.notify(err, severity="warning")
            return
        if payload is None:
            return
        self.query_one("#input", JarvisTextArea).clear()
        self._handle_user_message(payload)

    def _maybe_warn_ime_drift(self) -> None:
        """tui-ux13 L1：低频复检 IME shim 状态；非 installed 且未提示过 → 一次性 notify。"""
        if self._ime_drift_notified or sys.platform != "win32":
            return
        if ime_shim.shim_status() == "installed":
            return
        self._ime_drift_notified = True
        self.notify(
            "输入通道漂移，中文输入可能受影响，详见 /doctor",
            timeout=5,
        )

    def _stream_agent(
        self,
        user_input: str | list | None = None,
        *,
        checkpoint_id: str | None = None,
        image_input: str | None = None,
        image_fallback: str | None = None,
    ) -> None:
        """后台线程入口：组装 TurnPresenter 并驱动本轮（编排细节见 tui_turn.py）。"""
        TurnPresenter(
            self,
            user_input,
            checkpoint_id,
            image_input=image_input,
            image_fallback=image_fallback,
        ).run()

    async def _wait_modal_dismiss(self, inv: commands.ToolInvocation):
        """push PermissionModal 并等待 dismiss 结果（在 UI 线程执行）。"""
        gen = self._hitl_generation
        result_holder: dict[str, object] = {}
        done = asyncio.Event()

        def on_dismiss(result) -> None:
            result_holder["value"] = result
            done.set()

        self._maybe_warn_ime_drift()
        self.push_screen(
            PermissionModal(
                inv,
                vault_path=self._vault_path(),
                workspace_root=self._workspace_root(),
            ),
            on_dismiss,
        )
        await done.wait()
        if gen != self._hitl_generation:
            return None
        value = result_holder.get("value")
        return value if isinstance(value, dict) else None

    def _on_turn_incomplete(self, thread_id: str) -> None:
        self._mark_hitl_resolved(thread_id, set(self._pending_hitl_keys))
        self._pending_hitl_keys.clear()
        self._bump_hitl_generation()

    def _highlighted_session_id(self) -> str | None:
        sidebar = self._session_sidebar()
        if sidebar.option_count == 0:
            return None
        option = sidebar.get_option_at_index(sidebar.highlighted)
        if option is None or option.id is None:
            return None
        return str(option.id)

    def on_text_selected(self, event: events.TextSelected) -> None:
        """#01: 对话区鼠标拖选松开后自动复制系统剪贴板。

        Textual 8.2.8 中 TextSelected 由 Screen 在每次 MouseUp 时 post
        （bubble=True）——widget 级 handler 收不到，必须挂在 App。
        无选区（单击/选区外松开）时静默。
        """
        try:
            log = self.query_one("#messages", CopyableRichLog)
        except Exception:
            return
        if not log.copy_on_select:
            return
        ok, text = log.copy_selection_to_clipboard()
        if not text:
            return
        if ok:
            self.notify(f"已复制 {len(text)} 字符", timeout=2)
        else:
            self.notify("复制失败，请用 Ctrl+Insert", timeout=3)

    def _copy_to_clipboard(self, text: str, message: str) -> None:
        from src.tui_log import copy_text_to_system_clipboard

        ok = copy_text_to_system_clipboard(text)
        self.copy_to_clipboard(text)
        if ok:
            self.notify(message, timeout=2)
        else:
            self.notify("复制失败（CMD 下请用 Ctrl+Insert）", timeout=3)

    def _ime_hint_mode(self) -> str:
        """#02: 读 tui.ime_hint（off/on/auto），缺失或非法值回落 auto。"""
        if not self.config:
            return "auto"
        tui = getattr(self.config, "tui", None) or {}
        mode = str(tui.get("ime_hint", "auto")).strip().lower()
        return mode if mode in ("off", "on", "auto") else "auto"

    def action_copy_picker(self) -> None:
        """打开复制内容选择器（#01）；关闭后焦点回输入框。"""

        def after_close(_result) -> None:
            self.query_one("#input", JarvisTextArea).focus()

        self._maybe_warn_ime_drift()
        self.push_screen(CopyPickerModal(self), after_close)

    def action_copy_session_or_selection(self) -> None:
        """复制：侧边栏高亮会话 ID > 日志区拖选 > 当前 thread_id。"""
        sidebar = self._session_sidebar()
        if sidebar.has_focus:
            session_id = self._highlighted_session_id()
            if session_id:
                self._copy_to_clipboard(session_id, f"已复制: {session_id}")
                return
        log = self.query_one("#messages", CopyableRichLog)
        selected = log.selected_plain_text().strip()
        if selected:
            self._copy_to_clipboard(selected, "已复制选中文本")
            return
        if self.thread_id:
            self._copy_to_clipboard(self.thread_id, f"已复制当前会话: {self.thread_id}")
            return
        self.notify("Ctrl+B 打开侧边栏，选中会话后按 Y", timeout=3)

    def action_delete_highlighted_session(self) -> None:
        """侧边栏聚焦时删除高亮会话。"""
        sidebar = self._session_sidebar()
        if not sidebar.has_focus:
            self.notify("请先 Ctrl+B 打开侧边栏并选中会话", timeout=2)
            return
        session_id = self._highlighted_session_id()
        if not session_id:
            return
        text, new_thread = commands.delete_session(self.agent, session_id, self.thread_id)
        self._apply_command_result(text, new_thread)

    def action_copy_selection(self) -> None:
        self.action_copy_session_or_selection()

    def action_cancel(self) -> None:
        worker = self._worker
        if worker is not None and not worker.is_finished:
            log = self.query_one("#messages", CopyableRichLog)
            self._hide_ai_stream()
            self._bump_hitl_generation()
            log.write("[i][dim]（已取消）[/dim][/i]")
            self._show_cancel_banner()
            worker.cancel()
            return
        # 空闲：双 Esc（ESC_UNDO_WINDOW 内）撤回上一轮；单 Esc 不退出应用。
        now = monotonic()
        if self._esc_primed_at and now - self._esc_primed_at <= ESC_UNDO_WINDOW:
            self._esc_primed_at = 0.0
            self._trigger_implicit_undo()
        else:
            self._esc_primed_at = now
            self.notify(
                f"再按一次 Esc（{ESC_UNDO_WINDOW:g}s 内）可撤回上一轮",
                timeout=ESC_UNDO_WINDOW,
            )

    def action_new_session(self) -> None:
        import uuid

        old_thread = self.thread_id
        self._leave_current_thread(old_thread)
        new_thread = f"session-{uuid.uuid4().hex[:8]}"
        # #12: 清空旧内容 + 欢迎提示
        self._adopt_thread(new_thread, f"[b]已开启新会话 {new_thread}[/b]", clear=True)
        log = self.query_one("#messages", RichLog)
        self._write_system(log, "JARVIS 就绪。@ 引用路径，/ 命令；Tab 切换 Plan/Act。")