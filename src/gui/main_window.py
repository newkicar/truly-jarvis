"""GUI 主窗口（PySide6）：会话侧栏（占位）+ 对话区（QStackedWidget 每 thread 一栈）
+ 输入区 + 状态行。worker→主线程事件经 UiBridge 信号驱动，本模块只做渲染。

工单 01 范围：最小可对话窗口（真实模型、流式上屏、回合门、取消）。
工单 03/04/05/06… 在本文件上渐进扩展（输入区自动拉高 / 审批卡片 / 命名侧栏 / 工具详情）。
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src import commands
from src.gui.events import UiBridge
from src.gui.pane import ChatPane
from src.gui.runtime import GuiPresenter


class MainWindow(QMainWindow):
    def __init__(self, presenter: GuiPresenter, bridge: UiBridge) -> None:
        QMainWindow.__init__(self)
        self.presenter = presenter
        self.bridge = bridge
        self.panes: dict[str, ChatPane] = {}
        self.active_tid: str | None = None
        self._build_ui()
        self._wire_bridge()
        for tid in presenter.session_ids():
            self._ensure_pane(tid)
        first = list(self.panes)
        self._switch_to(first[0] if first else presenter.new_session_id())

    # ---- 结构
    def _build_ui(self) -> None:
        self.setWindowTitle(f"Jarvis GUI — {self.presenter.runtime.model_label}")
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QFrame()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        title = QLabel("<b>JARVIS</b>  会话")
        title.setStyleSheet("font-size:14px;")
        ll.addWidget(title)
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_clicked)
        ll.addWidget(self.session_list, stretch=1)
        self.btn_new = QPushButton("＋ 新会话")
        self.btn_new.clicked.connect(lambda: self._switch_to(self.presenter.new_session_id()))
        ll.addWidget(self.btn_new)
        self.running_badge = QLabel("")
        self.running_badge.setStyleSheet("color:#ffd75e; font-size:11px;")
        ll.addWidget(self.running_badge)
        root.addWidget(left)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(4, 4, 4, 4)
        ml.setSpacing(2)
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, stretch=1)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#bbbbbb; padding:2px;")
        ml.addWidget(self.status_label)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("输入消息（Enter 发送，Shift+Enter 换行）")
        self.input.setFixedHeight(30)
        self.input.installEventFilter(self)
        input_row = QHBoxLayout()
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_active)
        self.btn_send = QPushButton("发送")
        self.btn_send.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold;"
            " border-radius:4px; padding:2px 12px; }"
        )
        self.btn_send.clicked.connect(self._submit)
        input_row.addWidget(self.input, stretch=1)
        input_row.addWidget(self.btn_cancel)
        input_row.addWidget(self.btn_send)
        ml.addLayout(input_row)
        root.addWidget(mid, 1)

        self.setCentralWidget(central)
        self.resize(1060, 700)

    # ---- 事件过滤：Enter 发送 / Shift+Enter 换行
    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtGui import QKeyEvent

        if obj is self.input and isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False  # 换行走默认
                self._submit()
                return True
        return super().eventFilter(obj, event)

    # ---- 会话栈
    def _ensure_pane(self, tid: str) -> ChatPane:
        if tid in self.panes:
            return self.panes[tid]
        p = ChatPane(tid)
        for role, text in commands.thread_history_text(self.presenter.runtime.agent, tid, 40):
            if role == "user":
                p.append_user(text)
            elif role == "ai":
                p.append_fallback(text)
        self.stack.addWidget(p)
        self.panes[tid] = p
        return p

    def _switch_to(self, tid: str) -> None:
        p = self._ensure_pane(tid)
        self.active_tid = tid
        self.stack.setCurrentWidget(p)
        p.stick = True
        p.snap_to_bottom()
        self.refresh_sessions()
        self.input.setFocus()
        note = "（回合进行中，切走不影响执行）" if self.presenter.gate.is_running(tid) else ""
        self.status_label.setText(f"会话 {tid}{note}")

    def _on_session_clicked(self) -> None:
        it = self.session_list.currentItem()
        if it is not None:
            self._switch_to(it.data(Qt.UserRole))

    def refresh_sessions(self) -> None:
        self.session_list.clear()
        tids = self.presenter.session_ids()
        if self.active_tid and self.active_tid not in tids:
            tids = [self.active_tid] + tids
        for tid in tids:
            p = self._ensure_pane(tid)
            label = commands.session_label(self.presenter.runtime.agent, tid)
            mark = "▸ " if tid == self.active_tid else "   "
            run = " ⚡" if self.presenter.gate.is_running(tid) else ""
            it = QListWidgetItem(f"{mark}{label}{run}")
            it.setData(Qt.UserRole, tid)
            it.setToolTip(tid)
            self.session_list.addItem(it)
            if tid == self.active_tid:
                self.session_list.setCurrentItem(it)

    # ---- 发送 / 回合
    def _submit(self) -> None:
        raw = self.input.toPlainText()
        payload, note = commands.build_submission(
            raw, tuple(commands.virtual_path_mappings(self.presenter.runtime.config))
        )
        if note:
            self.status_label.setText(note)
            return
        if payload is None:
            return
        tid = self.active_tid
        p = self._ensure_pane(tid)
        p.append_user(payload)
        self.input.clear()
        verdict = self.presenter.start_turn(tid, payload)
        self.status_label.setText("已发送，执行中…" if verdict == "started" else "已排队，回合结束后自动续发")

    def _cancel_active(self) -> None:
        if self.active_tid:
            self.presenter.cancel(self.active_tid)

    # ---- 桥接（worker → 主线程渲染）
    def _wire_bridge(self) -> None:
        b = self.bridge
        b.message_delta.connect(self._on_delta)
        b.message_end.connect(self._on_msg_end)
        b.fallback.connect(self._on_fallback)
        b.tool_call.connect(self._on_tool)
        b.subagent.connect(self._on_subagent)
        b.status.connect(self._on_status)
        b.turn_done.connect(self._on_turn_done)
        b.refresh_sessions.connect(self.refresh_sessions)
        b.notify.connect(self._on_notify)

    def _on_delta(self, tid: str, delta: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.ai_delta(delta)

    def _on_msg_end(self, tid: str, text: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.ai_end(text)

    def _on_fallback(self, tid: str, text: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_fallback(text)

    def _on_tool(self, tid, name, args, err, output, depth) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_tool(name, args, err, output, depth)

    def _on_subagent(self, tid, name, status, depth) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.append_subagent(name, status, depth)

    def _on_status(self, tid: str, text: str) -> None:
        if tid == self.active_tid:
            self.status_label.setText(text)

    def _on_turn_done(self, tid: str, ok: bool) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.running = False
        self.refresh_sessions()

    def _on_notify(self, text: str) -> None:
        self.status_label.setText(text)
