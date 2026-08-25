"""Textual TUI 界面（对标 opencode 终端界面）。"""
import asyncio
import sys
from collections import defaultdict
from functools import partial
from pathlib import Path
from time import time
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, OptionList, RichLog, Static
from textual.widgets.option_list import Option
from textual.worker import Worker

from src import commands
from src.tui_completion import OverlayState, apply_suggestion, resolve_overlay_state
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


class PasteInput(Input):
    """支持系统剪贴板粘贴的输入框。

    三个粘贴入口各自的病因与对策：
    - ctrl+v：Textual 默认 action_paste 读 app.clipboard（只含 app 内复制的内容），
      对外部复制的文本永远粘贴空 → 覆盖为读 OS 剪贴板；
    - ctrl+shift+v：终端若把它当普通按键透传，Textual 无此绑定 → 显式补绑定；
    - 右键/中键：Textual 鼠标捕获使终端级右键粘贴失效 → 绑定鼠标键触发粘贴
      （button 2/3 覆盖 win32 驱动的右/中键，不碰左键选区）。
    """

    BINDINGS = [
        Binding("ctrl+shift+v", "paste", "粘贴", show=False),
        # #08 Plan/Act：输入框聚焦时 Tab 切换模式（widget 级绑定先于 Screen 的
        # focus_next；补全活跃时由 app.on_key 先行拦截，仍为接受建议）。
        Binding("tab", "app.toggle_mode", "Plan/Act", show=False),
        Binding("shift+tab", "app.toggle_mode_reverse", "Plan/Act 反向", show=False),
    ]

    def action_paste(self) -> None:
        self.run_worker(self._read_clipboard_worker, thread=True, exclusive=True)

    def _read_clipboard_worker(self) -> None:
        text = read_os_clipboard()
        if text:
            self.app.call_from_thread(self._apply_paste, text)

    def _apply_paste(self, text: str) -> None:
        line = text.splitlines()[0] if text else ""
        if not line:
            return
        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(line)
        else:
            self.replace(line, *selection)

    async def _on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button in (2, 3):
            event.stop()
            event.prevent_default()
            self.action_paste()
            return
        await super()._on_mouse_down(event)


class PermissionModal(ModalScreen):
    """HITL 审批覆盖层（对标 opencode permission dialog）。

    四按钮：放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)。
    dismiss 结果: dict{"decision": "approve"|"reject"|"always_approve"|"edit",
    "message": str?, "edited": {name, args}?}；"cancel" 表示放弃本轮。
    """

    BINDINGS = [
        Binding("a", "choose('approve')", "放行", show=False),
        Binding("s", "choose('always_approve')", "永久放行", show=False),
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
        height: 70%;
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
        height: 1fr;
        max-height: 12;
        overflow-y: auto;
        border: round $surface;
        background: $surface;
        margin: 1 0;
        padding: 0 1;
    }
    #perm_buttons {
        height: auto;
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
        with Static(id="perm_box"):
            yield Label(f"Tool: {self.inv.name}", id="perm_tool")
            yield Label(f"{self.path_label} {self.inv.path}", id="perm_path")
            preview = permission_preview(
                self.inv,
                vault_path=self.vault_path,
                workspace_root=self.workspace_root,
            )
            yield Static(preview, id="perm_preview")
            with Horizontal(id="perm_buttons"):
                yield Button("放行", id="btn_approve", variant="success")
                yield Button("永久放行", id="btn_always", variant="primary")
                yield Button("拒绝", id="btn_reject", variant="error")
                yield Button("编辑参数", id="btn_edit", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_approve":
            self.dismiss({"decision": "approve"})
        elif event.button.id == "btn_always":
            self.dismiss({"decision": "always_approve"})
        elif event.button.id == "btn_reject":
            self.dismiss({"decision": "reject"})
        elif event.button.id == "btn_edit":
            self.action_edit_params()

    def action_edit_params(self) -> None:
        def got_edited(result) -> None:
            if result is not None:
                self.dismiss({"decision": "edit", "edited": result})

        self.app.push_screen(EditParamsModal(self.inv.args), got_edited)

    def action_choose(self, decision: str) -> None:
        self.dismiss({"decision": decision})


class EditParamsModal(ModalScreen):
    """编辑工具参数（从权限审批进入），逐 key Input，留空用原值。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, args: dict):
        super().__init__()
        self.args = dict(args or {})

    def compose(self) -> ComposeResult:
        yield Label("编辑参数（留空使用原值）")
        for k, v in self.args.items():
            yield Input(str(v), placeholder=k, id=f"param_{k}", classes="param_input")
        with Horizontal():
            yield Button("确认", id="btn_ok", variant="primary")
            yield Button("取消", id="btn_cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_cancel":
            self.dismiss(None)
            return
        edited = {}
        for k in self.args:
            inp = self.query_one(f"#param_{k}", Input)
            val = inp.value.strip()
            edited[k] = val if val else self.args[k]
        self.dismiss(edited)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
        height: 1;
        border: none;
        background: transparent;
        color: $text;
        padding: 0;
    }

    #input:focus {
        border: none;
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
        self.title = "JARVIS"
        self._restore_theme()
        self._update_sub_title()

    def _config_path(self) -> Path:
        if self.config and getattr(self.config, "project_root", None):
            return self.config.project_root / "javis.json"
        return commands.project_root() / "javis.json"

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
        self.sub_title = "  ".join(parts)

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
        return bool(tui.get("copy_on_select", False))

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
                    yield PasteInput(placeholder="输入消息，/ 开头为命令，@ 引用路径", id="input")
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
        stream = self.query_one("#ai_stream", Static)
        stream.add_class("-active")

    def _hide_ai_stream(self) -> None:
        stream = self.query_one("#ai_stream", Static)
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
        spinner = self.query_one("#status_spinner", Static)
        spinner.remove_class("-active")
        spinner.update("")

    def _update_ai_stream(self, text: str) -> None:
        stream = self.query_one("#ai_stream", Static)
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
        panel = self.query_one("#todo_panel", Static)
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
            " 复制：对话区拖选（松开自动复制）；/copy-session 或 Ctrl+Insert。退出：/exit 或 Ctrl+Q。",
        )
        for line in self._startup_lines:
            self._write_system(log, line)
        self._refresh_session_sidebar()
        self.query_one("#input", Input).focus()
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
        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        log = self.query_one("#messages", RichLog)
        log.write(user_message_markup(text))
        if text == "/exit":
            self.exit()
            return
        if text == "/help":
            log.write(commands.TUI_HELP)
            return
        if text.startswith("/"):
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
                self._worker = self.run_worker(
                    partial(self._stream_agent, checkpoint_id=full_id), thread=True
                )
                return
            cmd = parts[0]
            log.write(system_message_markup(f"正在执行 {cmd}…"))
            self._worker = self.run_worker(partial(self._run_command_worker, text), thread=True)
            return
        self._show_spinner()
        self._worker = self.run_worker(partial(self._stream_agent, user_input=text), thread=True)

    def _run_command_worker(self, text: str) -> None:
        """后台线程执行可能阻塞的命令（/history、/fork 等）。"""
        try:
            result, new_thread, _replay_cid = commands.dispatch_command(
                self.agent, self.thread_id, text, self.sched
            )
        except Exception as exc:
            result, new_thread = f"命令失败: {exc}", None
        self.call_from_thread(self._apply_command_result, result, new_thread)

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

    def _apply_command_result(self, result: str, new_thread: str | None) -> None:
        log = self.query_one("#messages", RichLog)
        log.write(result)
        if new_thread:
            # 命令驱动的轻量切换（/delete-session、/fork）：不走
            # _leave_current_thread——命令层语义已定，此处仅接管新 id。
            self._adopt_thread(new_thread, f"[b]已切换到会话 {new_thread}[/b]")
        else:
            self._refresh_session_sidebar()
        self.query_one("#input", Input).focus()

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

    def _adopt_thread(self, thread_id: str, message: str) -> None:
        """接管新会话：换 id → 副标题 → 侧边栏 → 欢迎行。"""
        self.thread_id = thread_id
        self._update_sub_title()
        self._refresh_session_sidebar()
        log = self.query_one("#messages", RichLog)
        # #12: 新建会话时清空旧内容，切换会话时保留（由 _switch_session 处理加载）
        if "新会话" in message:
            log.clear()
        log.write(message)

    def _switch_session(self, thread_id: str) -> None:
        if not thread_id or thread_id == self.thread_id:
            return
        old_thread = self.thread_id
        self._leave_current_thread(old_thread)
        # #13: 清空旧内容，加载目标会话完整对话历史
        log = self.query_one("#messages", RichLog)
        log.clear()
        pairs = commands.thread_history_text(self.agent, thread_id)
        for role, content in pairs:
            if role == "user":
                log.write(user_message_markup(content))
            else:
                self._write_ai(log, content)
        # 接管新 id
        self.thread_id = thread_id
        self._update_sub_title()
        self._refresh_session_sidebar()
        if not pairs:
            log.write("[i][dim]（暂无历史）[/dim][/i]")
        log.write(f"[b]已切换到会话 {thread_id}[/b]")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "session_sidebar":
            return
        thread_id = event.option.id
        if thread_id is not None:
            self._switch_session(str(thread_id))
        self.query_one("#input", Input).focus()

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

    def _refresh_suggestions(self) -> None:
        inp = self.query_one("#input", Input)
        overlay = self._path_completion_overlay()
        state = resolve_overlay_state(
            inp.value,
            inp.cursor_position,
            vault_path=self._vault_path(),
            workspace_root=self._workspace_root(),
            memories_root=self._memories_root(),
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
        inp = self.query_one("#input", Input)
        overlay = self._path_completion_overlay()
        selected = overlay.selected_insert()
        if not selected or not self._overlay_state.active:
            return
        new_value, new_cursor = apply_suggestion(
            inp.value,
            self._overlay_state.at_index,
            inp.cursor_position,
            selected,
        )
        inp.value = new_value
        inp.cursor_position = new_cursor
        inp.focus()
        self._refresh_suggestions()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "input":
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

    def on_input_submitted(self, event: Input.Submitted) -> None:
        overlay = self._path_completion_overlay()
        overlay.hide()
        self._completion_active = False
        self._overlay_state = OverlayState(kind="none", at_index=0, items=())
        self._handle_user_message(event.value)

    def _stream_agent(
        self,
        user_input: str | None = None,
        *,
        checkpoint_id: str | None = None,
    ) -> None:
        """后台线程入口：组装 TurnPresenter 并驱动本轮（编排细节见 tui_turn.py）。"""
        TurnPresenter(self, user_input, checkpoint_id).run()

    async def _wait_modal_dismiss(self, inv: commands.ToolInvocation):
        """push PermissionModal 并等待 dismiss 结果（在 UI 线程执行）。"""
        gen = self._hitl_generation
        result_holder: dict[str, object] = {}
        done = asyncio.Event()

        def on_dismiss(result) -> None:
            result_holder["value"] = result
            done.set()

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

    def _copy_to_clipboard(self, text: str, message: str) -> None:
        from src.tui_log import copy_text_to_system_clipboard

        ok = copy_text_to_system_clipboard(text)
        self.copy_to_clipboard(text)
        if ok:
            self.notify(message, timeout=2)
        else:
            self.notify("复制失败（CMD 下请用 Ctrl+Insert）", timeout=3)

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
        if self._worker is not None:
            log = self.query_one("#messages", CopyableRichLog)
            self._hide_ai_stream()
            self._bump_hitl_generation()
            log.write("[i][dim]（已取消）[/dim][/i]")
            self._worker.cancel()

    def action_new_session(self) -> None:
        import uuid

        old_thread = self.thread_id
        self._leave_current_thread(old_thread)
        new_thread = f"session-{uuid.uuid4().hex[:8]}"
        self._adopt_thread(new_thread, f"[b]已开启新会话 {new_thread}[/b]")