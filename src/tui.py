"""Textual TUI 界面（对标 opencode 终端界面）。"""
import asyncio
import sys
from functools import partial
from pathlib import Path
from time import time
from typing import cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static
from textual.worker import Worker, get_current_worker

from src import commands, streaming
from src.tui_format import (
    DEFAULT_TUI_THEME,
    LEGACY_BAD_THEMES,
    AiStreamThrottler,
    ai_message_header_markup,
    ai_stream_renderable,
    format_tool_call,
    permission_preview,
    render_markdown,
    system_message_markup,
    user_message_markup,
)


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


class JarvisApp(App):
    """JARVIS TUI。BINDINGS: ctrl+c 退出、Tab 切换焦点、ctrl+n 新会话。"""

    BINDINGS = [
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+t", "change_theme", "切换主题"),
        Binding("escape", "cancel", "取消", show=False),
        Binding("ctrl+c", "quit", "退出", priority=True),
    ]

    CSS = """
    Screen {
        background: $background;
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

    #body {
        height: 1fr;
        min-height: 0;
        margin: 0;
    }

    #chat_frame {
        height: 1fr;
        margin: 0 1;
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
        margin: 1 1 1 1;
        border: round $primary;
        background: $panel;
        padding: 0 1;
    }

    #editor_frame:focus-within {
        border: round $accent;
    }

    #prompt {
        width: auto;
        min-width: 2;
        color: $accent;
        content-align: center middle;
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
    ):
        super().__init__()
        self.config = config
        self.agent = agent
        self.permission_state = permission_state
        self.sched = sched
        self.thread_id = thread_id
        self._mcp_tool_count = mcp_tool_count
        self._startup_lines = startup_lines or []
        self._worker: Worker | None = None
        self.title = "JARVIS"
        self._restore_theme()
        self._update_sub_title()

    def _config_path(self) -> Path:
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
        parts = [self.thread_id]
        if self._mcp_tool_count:
            parts.append(f"MCP:{self._mcp_tool_count}")
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
        return getattr(self.config, "memory_dir", Path(".")).parent

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            with Container(id="chat_frame"):
                with Vertical(id="chat_stack"):
                    yield RichLog(id="messages", wrap=True, markup=True, auto_scroll=True)
                    yield Static("", id="ai_stream")
            with Horizontal(id="editor_frame"):
                yield Static("›", id="prompt")
                yield Input(placeholder="输入消息，/ 开头为命令", id="input")
        yield Footer()

    def _write_system(self, log: RichLog, text: str) -> None:
        log.write(system_message_markup(text))

    def _write_ai(self, log: RichLog, text: str) -> None:
        log.write(ai_message_header_markup())
        log.write(render_markdown(text))
        log.write("")

    def _show_ai_stream(self) -> None:
        stream = self.query_one("#ai_stream", Static)
        stream.add_class("-active")

    def _hide_ai_stream(self) -> None:
        stream = self.query_one("#ai_stream", Static)
        stream.remove_class("-active")
        stream.update("")

    def _update_ai_stream(self, text: str) -> None:
        stream = self.query_one("#ai_stream", Static)
        stream.update(ai_stream_renderable(text))

    def _finalize_ai_stream(self, log: RichLog, text: str) -> None:
        self._hide_ai_stream()
        if text.strip():
            self._write_ai(log, text)

    def on_mount(self) -> None:
        log = self.query_one("#messages", RichLog)
        self._write_system(log, "JARVIS 就绪。输入 /help 查看命令，/exit 退出。")
        for line in self._startup_lines:
            self._write_system(log, line)
        self.query_one("#input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
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
            self._run_command(text)
            return
        self._worker = self.run_worker(partial(self._stream_turn, text), thread=True)

    def _run_command(self, text: str) -> None:
        log = self.query_one("#messages", RichLog)
        result, new_thread = commands.dispatch_command(self.agent, self.thread_id, text, self.sched)
        log.write(result)
        if new_thread:
            self.thread_id = new_thread
            self._update_sub_title()
            log.write(f"[b]已切换到会话 {new_thread}[/b]")

    def _stream_turn(self, user_input: str) -> None:
        """后台线程消费 stream_events(v3)，逐字写入 RichLog。"""
        worker = get_current_worker()
        started = time()
        log = cast(RichLog, self.call_from_thread(self.query_one, "#messages", RichLog))
        throttler = AiStreamThrottler()
        stream_active = False
        cancel_notified = False

        def cancelled() -> bool:
            return worker.is_cancelled

        def write_line(text: str) -> None:
            if not cancelled():
                self.call_from_thread(log.write, text)

        def reset_header() -> None:
            nonlocal stream_active
            throttler.reset()
            stream_active = False
            self.call_from_thread(self._hide_ai_stream)

        def refresh_stream(force: bool = False) -> None:
            nonlocal stream_active
            if cancelled() or not throttler.buffer:
                return
            if not stream_active:
                self.call_from_thread(self._show_ai_stream)
                stream_active = True
            if force or throttler.due():
                throttler.mark_refreshed()
                self.call_from_thread(self._update_ai_stream, throttler.buffer)

        def on_message_end(segment: str) -> None:
            if cancelled() or not segment.strip():
                return
            refresh_stream(force=True)
            self.call_from_thread(self._finalize_ai_stream, log, segment)
            throttler.reset()
            nonlocal stream_active
            stream_active = False

        def on_message_delta(delta: str) -> None:
            nonlocal cancel_notified
            if cancelled():
                if not cancel_notified:
                    on_cancelled()
                return
            throttler.append(delta)
            refresh_stream()

        def on_subagent(name: str, status: str, depth: int) -> None:
            indent = max(0, depth - 1)
            prefix = "  " * indent
            write_line(f"{prefix}[yellow]▌ [{name}] {status}[/yellow]")

        def on_tool_call(name: str, args: str, err: bool, output: str | None, depth: int) -> None:
            write_line(format_tool_call(name, args, error=err, output=output, indent=depth))

        def handle_interrupts(interrupts):
            return streaming.collect_interrupt_decisions(
                interrupts,
                lambda inv: self.call_from_thread(self._wait_modal_dismiss, inv),
                permission_state=self.permission_state,
                on_always_approve=lambda name: self.call_from_thread(
                    log.write, f"[b]已设置 {name} = allow（已写入 javis.json）[/b]"
                ),
            )

        def on_cancelled() -> None:
            nonlocal cancel_notified, stream_active
            cancel_notified = True
            stream_active = False
            self.call_from_thread(self._hide_ai_stream)
            write_line("[i][dim]（已取消）[/dim][/i]")

        ok = False
        try:
            ok = streaming.run_agent_turn(
                self.agent,
                self.thread_id,
                user_input,
                handle_interrupts=handle_interrupts,
                callbacks={
                    "on_subagent": on_subagent,
                    "on_tool_call": on_tool_call,
                    "on_message_delta": on_message_delta,
                    "on_message_end": on_message_end,
                },
                is_cancelled=cancelled,
                on_fallback_message=lambda text: self.call_from_thread(
                    self._finalize_ai_stream, log, text or throttler.buffer
                ),
                on_stream_start=reset_header,
                on_cancelled=on_cancelled,
            )
        finally:
            elapsed = time() - started
            model = getattr(self.config, "model_id", "") or "model"
            self.call_from_thread(self._hide_ai_stream)
            if cancelled() and not cancel_notified:
                write_line("[i][dim]（已取消）[/dim][/i]")
            elif not ok and not cancelled():
                write_line("[i][dim]（已放弃本轮）[/dim][/i]")
            elif ok:
                write_line(f"[dim]▌ {model} ({elapsed:.1f}s)[/dim]")
            write_line("")

    async def _wait_modal_dismiss(self, inv: commands.ToolInvocation):
        """push PermissionModal 并等待 dismiss 结果（在 UI 线程执行）。"""
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
        # 等待用户决定；UI 事件循环继续处理按钮/键位
        await done.wait()
        value = result_holder.get("value")
        return value if isinstance(value, dict) else None

    def action_cancel(self) -> None:
        if self._worker is not None:
            log = self.query_one("#messages", RichLog)
            self._hide_ai_stream()
            log.write("[i][dim]（已取消）[/dim][/i]")
            self._worker.cancel()

    def action_new_session(self) -> None:
        import uuid

        self.thread_id = f"session-{uuid.uuid4().hex[:8]}"
        self._update_sub_title()
        log = self.query_one("#messages", RichLog)
        log.write(f"[b]已开启新会话 {self.thread_id}[/b]")