"""PROTOTYPE — throwaway（T-006 GUI 骨架原型，详见 PROTOTYPE.md，勿当生产代码）。

一条命令运行（从 worktree 根目录）：
    D:\\python_env\\python.exe .scratch\\prototype\\gui_skeleton.py            # mock（默认，确定性 HITL 脚本）
    D:\\python_env\\python.exe .scratch\\prototype\\gui_skeleton.py --real    # 真实 LLM（需 worktree 根有 .env）
    D:\\python_env\\python.exe .scratch\\prototype\\gui_skeleton.py --smoke   # offscreen 自动审批冒烟（自检用）

验证的问题（LOGIC+UI 混合，结论写回 PROTOTYPE.md）：
  1. 状态模型——「每 thread 独立消息栈 + 会话切换=换栈不重建 runtime」+「同 thread 回合门」
     是否手感正确（切走再切回，在途流是否继续长、是否错串）。
  2. HITL 内联审批卡片（codex 式卡片+表单）四按钮 + 编辑参数 + Esc 放弃，
     走真实 collect_interrupt_decisions resume 契约的观感与等待语义。
  3. 流式 Markdown 两种渲染策略（150ms 合批重渲 vs 逐 token 即时）+ 粘底/Back-to-bottom 手感。
  4. 实证：Qt 原生中文 IME、选区复制（亲手点验，见 PROTOTYPE.md 清单）。
"""
from __future__ import annotations

import re
import sys
import threading
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from langgraph.checkpoint.sqlite import SqliteSaver

from src import commands, streaming
from src.agent import build_agent
from src.config import load_config
from src.permissions import build_permission_interrupts
from src.project_paths import ensure_user_home

PROTO_HOME = Path(__file__).resolve().parent / "proto_home"
RENDER_BATCH_MS = 150

# ---------------------------------------------------------------- 脚本化假模型（mock）

LEAD_EXEC = "（mock）先跑一条命令验证执行通道。"
LEAD_WRITE = "（mock）明白，改道：写文件方案。"
FINAL_MD = (
    "## 执行完成\n\n"
    "工具链路验证结果：\n\n"
    "- `execute`：HITL 审批 → 真实执行 → 结果回填 ✓\n"
    "- `write_file`：diff 预览卡片 → 审批 → 落盘 ✓\n"
    "- 流式 Markdown：代码块 / 列表 / 表格渲染\n\n"
    "```python\nprint('jarvis gui streaming ok')\n```\n\n"
    "| 步骤 | 状态 |\n|---|---|\n| 审批 | 通过 |\n| 执行 | 成功 |\n"
)


def _json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


class ScriptedMockModel(BaseChatModel):
    """确定性 HITL 脚本模型：execute 卡片 →（拒绝则改道 write_file 卡片）→ 最终回答。"""

    def _next_tool_calls(self, messages: list[BaseMessage]):
        # 只看最后一条 HumanMessage 之后的消息（「本轮」脚本状态机，不被历史轮污染）
        idx = max(
            (i for i, m in enumerate(messages) if getattr(m, "type", "") == "human"),
            default=-1,
        )
        scope = messages[idx + 1 :]
        last_ai_tc = None
        last_tool = None
        for m in scope:
            if isinstance(m, AIMessage) and m.tool_calls:
                last_ai_tc = m.tool_calls
            if getattr(m, "type", "") == "tool":
                last_tool = m
        if last_tool is None:
            return [
                {
                    "name": "execute",
                    "args": {"command": 'echo "hello jarvis gui"'},
                    "id": "call-mock-exec",
                    "type": "tool_call",
                }
            ]
        tool_text = last_tool.content or ""
        first_name = last_ai_tc[0]["name"] if last_ai_tc else "?"
        if first_name == "execute" and "拒绝" in tool_text:
            return [
                {
                    "name": "write_file",
                    "args": {
                        "file_path": "hello.txt",
                        "content": "hello from jarvis gui prototype\nsecond line\n",
                    },
                    "id": "call-mock-write",
                    "type": "tool_call",
                }
            ]
        return None  # 工具已执行成功 → 最终回答

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        tc = self._next_tool_calls(messages)
        if tc:
            lead = LEAD_EXEC if tc[0]["name"] == "execute" else LEAD_WRITE
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=lead, tool_calls=tc))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=FINAL_MD))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        tc = self._next_tool_calls(messages)
        if tc:
            lead = LEAD_EXEC if tc[0]["name"] == "execute" else LEAD_WRITE
            yield ChatGenerationChunk(message=AIMessageChunk(content=lead))
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_calls=tc))
            return
        text = FINAL_MD
        for i in range(0, len(text), 8):
            yield ChatGenerationChunk(message=AIMessageChunk(content=text[i : i + 8]))
            time.sleep(0.03)

    def bind_tools(self, tools, **kwargs):
        return self

    @property
    def _llm_type(self) -> str:
        return "jarvis-mock-scripted"


# ---------------------------------------------------------------- Markdown → Qt rich text

def md_to_qt_html(md: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(md)
    html = doc.toHtml()

    def _pre_sub(m):
        body = m.group(1).replace("\n", "<br>")
        return (
            '<span style="font-family: Consolas, \'Courier New\', monospace;'
            ' background-color: #161616; color: #dddddd;">' + body + "</span>"
        )

    html = re.sub(r"<pre>(?:<code>)?(.*?)</code></pre>", _pre_sub, html, flags=re.S)
    html = re.sub(r"<pre>(.*?)</pre>", _pre_sub, html, flags=re.S)
    return html


def _mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(10)
    return f


# ---------------------------------------------------------------- UI 桥（worker → 主线程）

class UiBridge(QObject):
    message_delta = Signal(str, str)
    message_end = Signal(str, str)
    fallback = Signal(str, str)
    tool_call = Signal(str, str, str, bool, str, int)
    subagent = Signal(str, str, str, int)
    status = Signal(str, str)
    turn_done = Signal(str, bool)
    create_card = Signal(str, object, str)
    refresh_sessions = Signal()
    notify = Signal(str)


class CardSession:
    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: dict | None = None


# ---------------------------------------------------------------- 审批卡片（内联）

class ApprovalCard(QFrame):
    """codex 式内联审批卡片：工具名 + 参数预览（permission_preview）+ 四按钮 + 编辑表单。

    放弃 = 放弃本轮（result None，与 TUI modal q 语义一致）——卡片尾部显式标注，
    避免用户以为「关卡=取消执行」（T-004 风险⑥）。
    """

    def __init__(self, inv, preview: str, on_decision, on_abandon, parent=None):
        super().__init__(parent)
        self._on_decision = on_decision
        self._on_abandon = on_abandon
        self._locked = False
        self._inv = inv
        self._editor_shown = False

        self.setObjectName("approval_card")
        self.setStyleSheet(
            "#approval_card { border: 1px solid #7a5c00; border-radius: 6px; background: #2a2517; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)

        head = QLabel(f"<b>需要审批 · {inv.name}</b>")
        head.setStyleSheet("color: #ffd75e; font-size: 14px;")
        outer.addWidget(head)

        if inv.path:
            p = QLabel(f"目标: {inv.path}")
            p.setStyleSheet("color: #bbbbbb;")
            outer.addWidget(p)

        if preview:
            pv = QLabel(preview)
            pv.setTextInteractionFlags(Qt.TextSelectableByMouse)
            pv.setWordWrap(True)
            pv.setFont(_mono_font())
            pv.setStyleSheet(
                "color: #c8c8c8; background: #1c1c1c; border-radius: 4px; padding: 4px;"
            )
            outer.addWidget(pv)

        note = QLabel("Esc 或「放弃本轮」= 放弃本轮（工具不会执行；不是取消整个任务）")
        note.setStyleSheet("color: #888888; font-size: 11px;")
        outer.addWidget(note)

        btns = QHBoxLayout()
        self.btn_approve = QPushButton("放行")
        self.btn_always = QPushButton("永久放行")
        self.btn_reject = QPushButton("拒绝")
        self.btn_edit = QPushButton("编辑参数")
        self.btn_giveup = QPushButton("放弃本轮")
        self.btn_approve.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; font-weight: bold;"
            " border-radius: 4px; padding: 4px 10px; }"
        )
        self.btn_reject.setStyleSheet(
            "QPushButton { background: #8e2020; color: white; border-radius: 4px; padding: 4px 10px; }"
        )
        for b in (self.btn_approve, self.btn_always, self.btn_reject, self.btn_edit, self.btn_giveup):
            btns.addWidget(b)
        outer.addLayout(btns)
        outer.addWidget(self._editor_slot())
        self.btn_approve.setFocus()

        self.btn_approve.clicked.connect(lambda: self._decide({"decision": "approve"}))
        self.btn_always.clicked.connect(lambda: self._decide({"decision": "always_approve"}))
        self.btn_reject.clicked.connect(lambda: self._decide({"decision": "reject"}))
        self.btn_giveup.clicked.connect(self._abandon)
        self.btn_edit.clicked.connect(self._open_editor)
        self.btn_edit.setEnabled(inv.name in ("execute", "write_file", "edit_file"))

    def _editor_slot(self) -> QFrame:
        slot = QFrame()
        slot.setVisible(False)
        self._editor_box = slot
        return slot

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and not self._locked:
            self._abandon()
        else:
            super().keyPressEvent(e)

    def _open_editor(self):
        if self._editor_shown or self._locked:
            return
        self._editor_shown = True
        inv = self._inv
        args = dict(inv.args or {})
        box = self._editor_box
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 4)
        label = QLabel("编辑参数（留空 = 保留原值）:")
        label.setStyleSheet("color: #bbbbbb;")
        bl.addWidget(label)
        single_line = inv.name == "execute"
        editors: list[tuple[str, QWidget]] = []
        for k, v in args.items():
            kl = QLabel(f"<b>{k}</b>（原值: {_clip(v, 80)}）")
            kl.setStyleSheet("color: #999999;")
            bl.addWidget(kl)
            if single_line:
                ed = QLineEdit(str(v or ""))
            else:
                ed = QPlainTextEdit(str(v or ""))
                ed.setFixedHeight(90)
            ed.setFont(_mono_font())
            bl.addWidget(ed)
            editors.append((k, ed))
        ok = QPushButton("确认编辑后放行")
        ok.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border-radius: 4px; padding: 4px 10px; }"
        )
        bl.addWidget(ok)

        def _confirm():
            edited = dict(args)
            for k, ed in editors:
                nv = ed.text() if isinstance(ed, QLineEdit) else ed.toPlainText()
                if nv:
                    edited[k] = nv
            self._decide({"decision": "edit", "edited": edited})

        ok.clicked.connect(_confirm)
        box.show()

    def _decide(self, result: dict):
        if self._locked:
            return
        self._locked = True
        for b in (self.btn_approve, self.btn_always, self.btn_reject, self.btn_edit, self.btn_giveup):
            b.setEnabled(False)
        text = {
            "approve": "已放行",
            "always_approve": "已永久放行（写入 jarvis.json）",
            "reject": "已拒绝",
            "edit": "已编辑参数并放行",
        }.get(result.get("decision"), "?")
        head = QLabel(f"<b>✓ {text}</b>")
        head.setStyleSheet("color: #6fd66f;")
        self.layout().addWidget(head)
        self._on_decision(result)

    def _abandon(self):
        if self._locked:
            return
        self._locked = True
        for b in (self.btn_approve, self.btn_always, self.btn_reject, self.btn_edit, self.btn_giveup):
            b.setEnabled(False)
        head = QLabel("<b>已放弃本轮（工具未执行）</b>")
        head.setStyleSheet("color: #e57373;")
        self.layout().addWidget(head)
        self._on_abandon()


def _clip(v, n: int) -> str:
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------- 每 thread 消息栈

class PaneState:
    __slots__ = (
        "tid", "scroll", "vbox", "spacer", "ai_label", "ai_buf", "dirty",
        "stick", "running", "started_at",
    )

    def __init__(self, tid: str):
        self.tid = tid
        self.scroll: QScrollArea | None = None
        self.vbox: QVBoxLayout | None = None
        self.spacer: QWidget | None = None
        self.ai_label: QLabel | None = None
        self.ai_buf = ""
        self.dirty = False
        self.stick = True
        self.running = False
        self.started_at = 0.0


# ---------------------------------------------------------------- 主控制器

class MainWindow(QObject):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.agent = ctx.agent
        self.config = ctx.config
        self.bridge = UiBridge()
        self.panes: dict[str, PaneState] = {}
        self.cards: dict[str, CardSession] = {}
        self.cancel_flags: dict[str, bool] = {}
        self.active_tid: str | None = None
        self.render_strategy = "batch"
        self._build_ui()
        self._wire_bridge()
        for tid in commands.session_thread_ids(self.agent):
            self._ensure_pane(tid)
        first = list(self.panes)
        self._switch_to(first[0] if first else self._new_session_id())
        self.refresh_sessions()
        self.window.show()

    # ---- 结构
    def _build_ui(self):
        self.window = QMainWindow()
        self.window.setWindowTitle(
            f"Jarvis GUI 原型 — {self.ctx.model_label} {self.ctx.proto_note}"
        )
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QFrame()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        title = QLabel("<b>JARVIS</b>  会话")
        title.setStyleSheet("font-size: 14px;")
        ll.addWidget(title)
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(lambda _it: self._on_session_clicked())
        ll.addWidget(self.session_list, stretch=1)
        self.btn_new_session = QPushButton("＋ 新会话")
        self.btn_new_session.clicked.connect(lambda: self._switch_to(self._new_session_id()))
        ll.addWidget(self.btn_new_session)

        strat_title = QLabel("流式渲染策略（实证）")
        strat_title.setStyleSheet("color: #999999; font-size: 11px;")
        ll.addWidget(strat_title)
        self.rb_batch = QRadioButton(f"合批重渲（{RENDER_BATCH_MS}ms）")
        self.rb_instant = QRadioButton("逐 token 即时")
        self.rb_batch.setChecked(True)
        self.rb_batch.toggled.connect(
            lambda on: setattr(self, "render_strategy", "batch" if on else "instant")
        )
        ll.addWidget(self.rb_batch)
        ll.addWidget(self.rb_instant)

        self.running_badge = QLabel("")
        self.running_badge.setStyleSheet("color: #ffd75e; font-size: 11px;")
        ll.addWidget(self.running_badge)
        root.addWidget(left)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.setSpacing(2)
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, stretch=1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #bbbbbb; padding: 2px;")
        self.btn_back = QPushButton("↓ 回到底部")
        self.btn_back.setVisible(False)
        self.btn_back.clicked.connect(self._back_to_bottom)
        self.btn_back.setStyleSheet(
            "QPushButton { background: #1565c0; color: white; border-radius: 4px; padding: 2px 8px; }"
        )
        bottom.addWidget(self.status_label, stretch=1)
        bottom.addWidget(self.btn_back)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入消息（Enter 发送，Shift+Enter 换行；中文输入法直接打）")
        self.input.setFixedHeight(30)
        self.input.installEventFilter(self)
        input_row = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_active)
        self.btn_send = QPushButton("发送")
        self.btn_send.setStyleSheet(
            "QPushButton { background: #2e7d32; color: white; font-weight: bold;"
            " border-radius: 4px; padding: 2px 12px; }"
        )
        self.btn_send.clicked.connect(self._submit)
        input_row.addWidget(self.input, stretch=1)
        input_row.addWidget(self.btn_cancel)
        input_row.addWidget(self.btn_send)
        ml.addLayout(input_row)
        root.addWidget(mid, 1)

        self.window.setCentralWidget(central)
        self.window.resize(1060, 700)

        self.render_timer = QTimer()
        self.render_timer.setInterval(RENDER_BATCH_MS)
        self.render_timer.timeout.connect(self._render_dirty)
        self.render_timer.start()
        self._watchdog = QTimer()
        self._watchdog.setInterval(400)
        self._watchdog.timeout.connect(self._watch_tick)
        self._watchdog.start()

    def _watch_tick(self):
        running = [t for t, p in self.panes.items() if p.running]
        self.running_badge.setText("执行中: " + ", ".join(running) if running else "")
        self.btn_cancel.setEnabled(bool(running))

    def eventFilter(self, obj, event):
        if obj is self.input and isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ShiftModifier):
                self._submit()
                return True
        return super().eventFilter(obj, event)

    # ---- 会话栈
    def _new_session_id(self) -> str:
        return f"session-{uuid.uuid4().hex[:8]}"

    def _ensure_pane(self, tid: str) -> PaneState:
        if tid in self.panes:
            return self.panes[tid]
        p = PaneState(tid)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        vbox = QVBoxLayout(inner)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(6)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vbox.addWidget(spacer, stretch=1)
        sa.setWidget(inner)
        sa.verticalScrollBar().valueChanged.connect(lambda _v: self._on_scroll_changed(tid))
        sa.verticalScrollBar().rangeChanged.connect(lambda _a, _b: self._on_scroll_range(tid))
        self.stack.addWidget(sa)
        self.panes[tid] = p
        p.scroll = sa
        p.vbox = vbox
        p.spacer = spacer
        # 历史回放（本 app 启动前已固化的会话）
        for role, text in commands.thread_history_text(self.agent, tid, 40):
            if role == "user":
                self._append_block(p, self._user_label(text))
            elif role == "ai":
                self._append_block(p, self._ai_label(text))
        return p

    def _append_block(self, p: PaneState, widget: QWidget):
        p.vbox.insertWidget(p.vbox.count() - 1, widget)

    def _user_label(self, text: str) -> QLabel:
        l = QLabel(f"[你] {text}")
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setTextFormat(Qt.PlainText)
        l.setStyleSheet(
            "color: #e8e8e8; background: #1f3a5f; border-radius: 4px; padding: 4px;"
        )
        return l

    def _ai_label(self, md_text: str) -> QLabel:
        l = QLabel()
        l.setTextFormat(Qt.RichText)
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setStyleSheet("background: #101820; border-radius: 4px; padding: 6px;")
        l.setText(md_to_qt_html(md_text))
        return l

    def _tool_label(self, name, args, err, output, depth) -> QLabel:
        mark = "✗" if err else "✓"
        color = "#e57373" if err else "#7fbf7f"
        out = str(output or "")
        if len(out) > 200:
            out = out[:200] + "…"
        line = f"{'  ' * depth}{mark} {name}({str(args)[:120]})"
        if out:
            line += f"  → {out}"
        l = QLabel(line)
        l.setTextFormat(Qt.PlainText)
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setFont(_mono_font())
        l.setStyleSheet(f"color: {color}; font-size: 12px;")
        return l

    def _subagent_label(self, name, status, depth) -> QLabel:
        l = QLabel(f"{'  ' * depth}[{name}] {status}")
        l.setStyleSheet("color: #ffd75e; font-size: 12px;")
        l.setTextFormat(Qt.PlainText)
        return l

    def _switch_to(self, tid: str):
        p = self._ensure_pane(tid)
        self.active_tid = tid
        self.stack.setCurrentWidget(p.scroll)
        p.stick = True
        self._snap_to_bottom(p)
        self.refresh_sessions()
        self.input.setFocus()
        self.status_label.setText(
            f"会话 {tid}" + ("（回合进行中，切走不影响执行）" if p.running else "")
        )

    def _on_session_clicked(self):
        it = self.session_list.currentItem()
        if it is not None:
            self._switch_to(it.data(Qt.UserRole))

    def refresh_sessions(self):
        self.session_list.clear()
        tids = commands.session_thread_ids(self.agent)
        if self.active_tid and self.active_tid not in tids:
            tids = [self.active_tid] + tids
        for tid in tids:
            p = self._ensure_pane(tid)
            label = commands.session_label(self.agent, tid)
            mark = "▸ " if tid == self.active_tid else "   "
            run = " ⚡" if p.running else ""
            it = QListWidgetItem(f"{mark}{label}{run}")
            it.setData(Qt.UserRole, tid)
            it.setToolTip(tid)
            self.session_list.addItem(it)
            if tid == self.active_tid:
                self.session_list.setCurrentItem(it)

    # ---- 滚动/粘底（tui-ux16r2 状态机平移）
    def _on_scroll_changed(self, tid: str):
        p = self.panes.get(tid)
        if p is None:
            return
        sb = p.scroll.verticalScrollBar()
        if sb.value() >= sb.maximum() - 2:
            p.stick = True
            if tid == self.active_tid:
                self.btn_back.setVisible(False)
        else:
            p.stick = False
            if tid == self.active_tid:
                self.btn_back.setVisible(True)

    def _on_scroll_range(self, tid: str):
        p = self.panes.get(tid)
        if p is None:
            return
        if tid != self.active_tid:
            return
        if p.stick:
            self._snap_to_bottom(p)
        else:
            self.btn_back.setVisible(True)

    def _snap_to_bottom(self, p: PaneState):
        sb = p.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        p.stick = True
        if p.tid == self.active_tid:
            self.btn_back.setVisible(False)

    def _back_to_bottom(self):
        p = self.panes.get(self.active_tid or "")
        if p is not None:
            self._snap_to_bottom(p)

    # ---- 流事件渲染
    def _render_dirty(self):
        for tid, p in self.panes.items():
            if p.dirty and p.ai_label is not None:
                p.ai_label.setText(md_to_qt_html(p.ai_buf))
                p.dirty = False
                if p.stick or tid != self.active_tid:
                    self._snap_to_bottom(p)

    def _on_delta(self, tid: str, delta: str):
        p = self.panes.get(tid)
        if p is None:
            return
        p.ai_buf += delta
        if p.ai_label is None:
            p.ai_label = self._ai_label(p.ai_buf)
            self._append_block(p, p.ai_label)
        if self.render_strategy == "instant":
            p.ai_label.setText(md_to_qt_html(p.ai_buf))
            p.dirty = False
            if p.stick or tid != self.active_tid:
                self._snap_to_bottom(p)
        else:
            p.dirty = True

    def _on_msg_end(self, tid: str, text: str):
        p = self.panes.get(tid)
        if p is None:
            return
        if p.ai_label is not None:
            p.ai_label.setText(md_to_qt_html(p.ai_buf or text))
            p.ai_label = None
            p.ai_buf = ""
            p.dirty = False
            if p.stick or tid != self.active_tid:
                self._snap_to_bottom(p)
        elif text:
            self._append_block(p, self._ai_label(text))
            if p.stick or tid != self.active_tid:
                self._snap_to_bottom(p)

    def _on_fallback(self, tid: str, text: str):
        p = self.panes.get(tid)
        if p is None or not text:
            return
        self._append_block(p, self._ai_label(text))
        if p.stick or tid != self.active_tid:
            self._snap_to_bottom(p)

    def _on_tool(self, tid, name, args, err, output, depth):
        p = self.panes.get(tid)
        if p is None:
            return
        self._append_block(p, self._tool_label(name, args, err, output, depth))
        if p.stick or tid != self.active_tid:
            self._snap_to_bottom(p)

    def _on_subagent(self, tid, name, status, depth):
        p = self.panes.get(tid)
        if p is None:
            return
        self._append_block(p, self._subagent_label(name, status, depth))
        if p.stick or tid != self.active_tid:
            self._snap_to_bottom(p)

    def _on_status(self, tid: str, text: str):
        if tid == self.active_tid:
            self.status_label.setText(text)

    def _on_turn_done(self, tid: str, ok: bool):
        p = self.panes.get(tid)
        if p is not None:
            p.running = False
        self.refresh_sessions()

    # ---- 发送/回合
    def _submit(self):
        raw = self.input.toPlainText()
        payload, note = commands.build_submission(
            raw, tuple(commands.virtual_path_mappings(self.config))
        )
        if note:
            self.status_label.setText(note)
            return
        if payload is None:
            return
        tid = self.active_tid
        p = self._ensure_pane(tid)
        self._append_block(p, self._user_label(payload))
        self.input.clear()
        if p.stick:
            self._snap_to_bottom(p)
        self._start_turn(tid, payload)

    def _start_turn(self, tid: str, user_text: str):
        p = self.panes[tid]
        if p.running:
            self.status_label.setText("该会话已有回合在进行；等它结束（或点「取消」）再发。")
            return
        p.running = True
        p.started_at = time.monotonic()
        self.cancel_flags[tid] = False
        th = threading.Thread(
            target=self._turn_worker, args=(tid, user_text), daemon=True, name=f"jarvis-gui-turn-{tid[:10]}"
        )
        self.ctx.turns[tid] = th
        th.start()

    def _turn_worker(self, tid: str, user_text: str):
        agent = self.agent
        b = self.bridge
        t0 = time.monotonic()
        try:
            ok = streaming.run_agent_turn(
                agent,
                tid,
                user_text,
                handle_interrupts=lambda its: self._handle_interrupts(its, tid),
                callbacks={
                    "on_message_delta": lambda d: b.message_delta.emit(tid, d),
                    "on_message_end": lambda t: b.message_end.emit(tid, t),
                    "on_tool_call": lambda n, a, e, o=None, depth=0: b.tool_call.emit(
                        tid, n, a, e, o or "", depth
                    ),
                    "on_subagent": lambda n, s, depth=0: b.subagent.emit(tid, n, s, depth),
                    "on_status": lambda s: b.status.emit(tid, s),
                },
                on_fallback_message=lambda t: b.fallback.emit(tid, t),
                is_cancelled=lambda: self.cancel_flags.get(tid, False),
                permission_state=self.ctx.permission_state,
                project_root=self.config.project_root,
            )
            b.turn_done.emit(tid, bool(ok))
            b.notify.emit(f"回合{'完成' if ok else '放弃/取消'}（{time.monotonic() - t0:.1f}s）")
        except Exception as exc:
            b.turn_done.emit(tid, False)
            b.notify.emit(streaming.format_agent_error(exc))
        finally:
            self.panes[tid].running = False
            self.cancel_flags[tid] = False
            b.refresh_sessions.emit()

    def _handle_interrupts(self, interrupts, tid: str):
        return streaming.collect_interrupt_decisions(
            interrupts,
            lambda inv: self._card_ask(inv, tid),
            permission_state=self.ctx.permission_state,
            on_always_approve=lambda n: self.bridge.notify.emit(
                f"已永久放行 {n}（写入 jarvis.json，以后自动放行）"
            ),
        )

    def _card_ask(self, inv, tid: str) -> dict | None:
        from src.tui_format import permission_preview

        preview = permission_preview(
            inv, vault_path=self.config.vault_path, workspace_root=self.config.project_root
        )
        card_id = uuid.uuid4().hex
        cs = CardSession()
        self.cards[card_id] = cs
        self.bridge.notify.emit(f"等待审批 {inv.name}…")

        def on_decision(result: dict):
            cs.result = result
            cs.event.set()

        def on_abandon():
            cs.result = None
            cs.event.set()

        self.bridge.create_card.emit(
            tid, (inv, preview, card_id, on_decision, on_abandon), card_id
        )
        cs.event.wait()
        self.cards.pop(card_id, None)
        return cs.result

    def _on_create_card(self, tid, payload, card_id: str):
        inv, preview, card_id, on_decision, on_abandon = payload
        p = self.panes.get(tid)
        if p is None:
            return
        card = ApprovalCard(
            inv,
            preview,
            on_decision,
            on_abandon,
        )
        self._append_block(p, card)
        if p.stick or tid != self.active_tid:
            self._snap_to_bottom(p)

    # ---- 取消
    def _cancel_active(self):
        if self.active_tid:
            self.cancel_flags[self.active_tid] = True
            self.status_label.setText("已取消，正在收尾（当前步骤结束后停止）")

    # ---- 桥接
    def _wire_bridge(self):
        b = self.bridge
        b.message_delta.connect(self._on_delta)
        b.message_end.connect(self._on_msg_end)
        b.fallback.connect(self._on_fallback)
        b.tool_call.connect(self._on_tool)
        b.subagent.connect(self._on_subagent)
        b.status.connect(self._on_status)
        b.turn_done.connect(self._on_turn_done)
        b.create_card.connect(self._on_create_card)
        b.refresh_sessions.connect(lambda: self.refresh_sessions())
        b.notify.connect(lambda s: self.status_label.setText(s))


# ---------------------------------------------------------------- 装配


def _ensure_proto_home() -> Path:
    PROTO_HOME.mkdir(parents=True, exist_ok=True)
    (PROTO_HOME / "checkpoints").mkdir(exist_ok=True)
    (PROTO_HOME / "memory").mkdir(exist_ok=True)
    if not (PROTO_HOME / "jarvis.json").exists():
        (PROTO_HOME / "jarvis.json").write_text(
            "{\n  \"permissions\": {\"execute\": {\"*\": \"ask\"}, \"write_file\": {\"*\": \"ask\"}}\n}\n",
            encoding="utf-8",
        )
    if not (PROTO_HOME / ".env").exists():
        (PROTO_HOME / ".env").write_text(
            "BASE_URL=http://mock.local/v1\nAPI_KEY=mock-key\nMODEL_ID=mock\nTAVILY_KEY=mock\n",
            encoding="utf-8",
        )
    return PROTO_HOME


def main(argv: list[str]) -> int:
    real = "--real" in argv
    smoke = "--smoke" in argv
    if smoke:
        import os

        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    ensure_user_home()
    if real:
        try:
            config = load_config()
        except (KeyError, FileNotFoundError) as exc:
            print(f"真实模式需要 worktree 根的项目配置（{exc}）。")
            print(
                "先执行（两者均为本地 gitignore 文件）：\n"
                'copy "D:\\Python Project\\truly-jarvis-main\\jarvis.json" .\\jarvis.json\n'
                'copy "D:\\Python Project\\truly-jarvis-main\\.env" .\\.env\n'
                "再重试 --real。"
            )
            return 1
        model = None
        model_label = config.model_id
        proto_note = "（真实模型）"
    else:
        home = _ensure_proto_home()
        config = load_config(project_root=home)
        model = ScriptedMockModel()
        model_label = "scripted-mock"
        proto_note = "（mock 模式：确定性 HITL 脚本——拒绝 execute 会自动改道 write_file 卡片）"

    from src.jump_in_queue import JumpInRegistry

    ctx = type("Ctx", (), {})()
    ctx.agent = None
    ctx.config = config
    ctx.model_label = model_label
    ctx.proto_note = proto_note
    ctx.turns = {}
    ctx.permission_state = None

    registry = JumpInRegistry()
    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        checkpointer.setup()
        _, permission_state = build_permission_interrupts(
            config.permissions, hooks=config.hooks, project_root=config.project_root
        )
        ctx.permission_state = permission_state
        ctx.agent = build_agent(
            config,
            model=model,
            checkpointer=checkpointer,
            permission_state=permission_state,
            jump_in_registry=registry,
        )

        app = QApplication.instance() or QApplication(sys.argv[:1])
        win = MainWindow(ctx)

        if smoke:
            tid = win._new_session_id()
            win._switch_to(tid)
            win._append_block(win.panes[tid], win._user_label("smoke: 跑一遍 HITL"))

            def wait_for_card(expect_name: str, timeout: float = 60.0) -> ApprovalCard:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    app.processEvents()
                    for i in range(win.panes[tid].vbox.count()):
                        w = win.panes[tid].vbox.itemAt(i).widget()
                        if (
                            isinstance(w, ApprovalCard)
                            and not w._locked
                            and w._inv.name == expect_name
                        ):
                            return w
                    time.sleep(0.02)
                raise AssertionError(f"smoke: 未等到 {expect_name} 卡片")

            # 阶段 1：非阻塞自动放行（验证卡片之外的全链路）
            orig_ask = win._card_ask
            win._card_ask = lambda inv, _tid: {"decision": "approve"}
            win._start_turn(tid, "smoke")
            deadline = time.monotonic() + 90
            while win.panes[tid].running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.05)
            win._card_ask = orig_ask
            if win.panes[tid].running:
                print("SMOKE FAIL: 阶段1 回合 90s 内未结束")
                return 1
            print("SMOKE 阶段1 OK: 完整一轮（HITL 自动放行 + 工具执行 + 最终回答 + 落盘检查点）")

            # 阶段 2：真实阻塞卡片循环——拒绝 execute → 改道 write_file → 放行（验证卡片渲染+四按钮+diff）
            win._start_turn(tid, "再来一轮：这次先拒绝")
            card1 = wait_for_card("execute")
            card1.btn_reject.click()
            card2 = wait_for_card("write_file")
            card2.btn_approve.click()
            deadline = time.monotonic() + 90
            while win.panes[tid].running and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.05)
            if win.panes[tid].running:
                print("SMOKE FAIL: 阶段2 回合 90s 内未结束")
                return 1
            for _ in range(20):
                app.processEvents()
            tool_lines = [
                w.text()[:90]
                for i in range(win.panes[tid].vbox.count())
                for w in [win.panes[tid].vbox.itemAt(i).widget()]
                if isinstance(w, QLabel)
                and (w.text().startswith("✓") or w.text().startswith("✗"))
            ]
            print("SMOKE dbg status:", win.status_label.text(), "| tools:", tool_lines)
            hello = PROTO_HOME / "hello.txt"
            if not hello.is_file() or "jarvis gui" not in hello.read_text(encoding="utf-8"):
                print(f"SMOKE FAIL: {hello} 未写入或内容不符")
                return 1
            print("SMOKE 阶段2 OK: 拒绝→改道 write_file→放行 双卡片循环 + 文件落盘")
            print("SMOKE OK: 两阶段全绿")
            return 0

        app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
