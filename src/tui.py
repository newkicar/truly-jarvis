"""Textual TUI 界面（对标 opencode 终端界面）。

结构：
- JarvisApp: 主 App，Header + 消息区 RichLog + Input + Footer
- 命令路由：`/` 前缀 → commands.dispatch_command；普通文本 → 流式对话
- 流式：@work(thread=True) 消费 stream_events(v3)，call_from_thread 逐字写 RichLog；
  工具/子代理即时显示，Esc 取消当前轮次
- 消息样式：用户 secondary 粗竖线、AI primary 粗竖线 + 模型/耗时、工具 muted、子代理黄
- HITL 审批：stream.interrupts → PermissionModal（放行/永久放行/拒绝/编辑参数）→ resume
"""
import asyncio
from functools import partial
from time import time
from typing import cast

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Static
from textual.worker import Worker, get_current_worker

from src import commands


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

    def __init__(self, inv: commands.ToolInvocation):
        super().__init__()
        self.inv = inv
        self.path_label = "Command:" if inv.name == "execute" else "Path:"

    def compose(self) -> ComposeResult:
        with Static(id="perm_box"):
            yield Label(f"Tool: {self.inv.name}", id="perm_tool")
            yield Label(f"{self.path_label} {self.inv.path}", id="perm_path")
            preview_lines = "\n".join(f"{k}: {str(v)[:120]}" for k, v in (self.inv.args or {}).items())
            yield Static(preview_lines or "（无参数）", id="perm_preview")
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
        Binding("escape", "cancel", "取消", show=False),
        Binding("ctrl+c", "quit", "退出", priority=True),
    ]

    CSS = """
    #messages {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $surface;
    }
    #input {
        dock: bottom;
        margin: 1 2 1 2;
    }
    """

    def __init__(self, config, agent, permission_state: dict, sched=None, thread_id: str = "default", mcp_tool_count: int = 0):
        super().__init__()
        self.config = config
        self.agent = agent
        self.permission_state = permission_state
        self.sched = sched
        self.thread_id = thread_id
        self._mcp_tool_count = mcp_tool_count
        self._worker: Worker | None = None
        self.title = "JARVIS"
        self._update_sub_title()

    def _update_sub_title(self) -> None:
        mcp_tag = f"  MCP:{self._mcp_tool_count}" if self._mcp_tool_count else ""
        self.sub_title = f"{self.thread_id}{mcp_tag}"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="messages", wrap=True, markup=True)
        yield Input(placeholder="输入消息（/ 开头为命令，ctrl+c 退出，Esc 取消本轮）", id="input")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#messages", RichLog)
        log.write("JARVIS 就绪。输入 /help 查看命令，/exit 退出。")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        input_widget = self.query_one("#input", Input)
        input_widget.value = ""
        log = self.query_one("#messages", RichLog)
        log.write(f"[b][secondary]▌[/secondary][/b] [b]You[/b] {text}")
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
        from langgraph.types import Command

        config = {"configurable": {"thread_id": self.thread_id}, "recursion_limit": 30}
        worker = get_current_worker()
        started = time()
        log = cast(RichLog, self.call_from_thread(self.query_one, "#messages", RichLog))

        def cancelled() -> bool:
            return worker.is_cancelled

        def write_line(text: str) -> None:
            if not cancelled():
                self.call_from_thread(log.write, text)

        resume = None
        while not cancelled():
            stream = self.agent.stream_events(
                Command(resume=resume)
                if resume
                else {"messages": [{"role": "user", "content": user_input}]},
                version="v3",
                config=config,
            )

            consumed = 0
            for kind, item in stream.interleave("messages", "tool_calls", "subagents"):
                if cancelled():
                    self.call_from_thread(log.write, "[i][dim]（已取消）[/dim][/i]")
                    return
                if kind == "subagents":
                    status = getattr(item, "status", "")
                    write_line(f"[yellow]▌ [{item.name}] {status}[/yellow]")
                elif kind == "tool_calls":
                    err = getattr(item, "error", None)
                    name = getattr(item, "tool_name", "?")
                    args = getattr(item, "input", "")
                    tag = "✗" if err else "✓"
                    write_line(f"[dim]  {tag} {name}({str(args)[:80]})[/dim]")
                else:  # messages
                    for delta in item.text:
                        consumed += 1
                        if not cancelled():
                            self.call_from_thread(log.write, f"[b][primary]▌ JARVIS[/primary][/b] {delta}", scroll_end=True)

            elapsed = time() - started
            model = getattr(self.config, "model_id", "") or "model"
            if not consumed:
                final_state = stream.output
                final_text = commands.render(final_state["messages"]) if final_state else ""
                if final_text:
                    write_line(f"[b][primary]▌ JARVIS[/primary][/b] {final_text}")

            if not getattr(stream, "interrupted", False) or not getattr(stream, "interrupts", None):
                write_line(f"[dim]▌ {model} ({elapsed:.1f}s)[/dim]")
                write_line("")
                return

            # HITL 审批：弹 Modal 收集决策，返回 resume dict（外层包 Command）
            resume = self._tui_handle_interrupts(stream.interrupts)
            if resume is None:
                write_line("[i][dim]（已放弃本轮）[/dim][/i]")
                write_line("")
                return

    def _tui_handle_interrupts(self, interrupts):
        """TUI 审批：逐条弹 PermissionModal，收集决策返回 resume dict。

        在 worker 线程调用；call_from_thread 会在 UI 线程 push 模态并阻塞等待
        dismiss 结果。任一中断放弃（cancel）→ 返回 None（放弃本轮）。

        返回结构与 CLI _handle_interrupts 契约一致：{"decisions": [...]}。
        外层循环负责包成 Command(resume=...)，此处只返回纯 dict（不重复包装）。
        """
        decisions = []
        for interrupt in interrupts:
            value = getattr(interrupt, "value", None) or {}
            action_requests = value.get("action_requests", [])
            for action in action_requests:
                inv = commands.ToolInvocation.from_action(action)
                result = self.call_from_thread(
                    self._push_permission_modal, inv
                )
                if result is None:
                    return None
                decision = result.get("decision")
                if decision == "approve":
                    decisions.append({"type": "approve"})
                elif decision == "reject":
                    decisions.append(
                        {"type": "reject", "message": "用户拒绝了该操作，请更换方案或询问用户。不要重试相同调用。"}
                    )
                elif decision == "always_approve":
                    if self.permission_state and commands.always_approve(self.permission_state, inv.name):
                        self.call_from_thread(
                            self.query_one("#messages", RichLog).write,
                            f"[b]已设置 {inv.name} = allow（已写入 javis.json）[/b]",
                        )
                    decisions.append({"type": "approve"})
                elif decision == "edit":
                    edited = result.get("edited") or {}
                    decisions.append(
                        {"type": "edit", "edited_action": {"name": inv.name, "args": edited}}
                    )
                else:  # cancel
                    return None
        return {"decisions": decisions}

    async def _push_permission_modal(self, inv: commands.ToolInvocation):
        return await self._wait_modal_dismiss(inv)

    async def _wait_modal_dismiss(self, inv: commands.ToolInvocation):
        """push PermissionModal 并等待 dismiss 结果（在 UI 线程执行）。"""
        result_holder: dict[str, object] = {}
        done = asyncio.Event()

        def on_dismiss(result) -> None:
            result_holder["value"] = result
            done.set()

        self.push_screen(PermissionModal(inv), on_dismiss)
        # 等待用户决定；UI 事件循环继续处理按钮/键位
        await done.wait()
        value = result_holder.get("value")
        return value if isinstance(value, dict) else None

    def action_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def action_new_session(self) -> None:
        import uuid

        self.thread_id = f"session-{uuid.uuid4().hex[:8]}"
        self._update_sub_title()
        log = self.query_one("#messages", RichLog)
        log.write(f"[b]已开启新会话 {self.thread_id}[/b]")