"""GUI 主窗口（PySide6）：会话侧栏（占位）+ 对话区（QStackedWidget 每 thread 一栈）
+ 输入区 + 状态行。worker→主线程事件经 UiBridge 信号驱动，本模块只做渲染。

工单 01 范围：最小可对话窗口（真实模型、流式上屏、回合门、取消）。
工单 03/04/05/06… 在本文件上渐进扩展（输入区自动拉高 / 审批卡片 / 命名侧栏 / 工具详情）。
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src import commands
from src import clipboard_image
from src.gui.events import UiBridge
from src.gui.image_strip import build_image_submit, save_clipboard_image_to_temp
from src.gui.image_widgets import ImageStrip
from src.gui.input_bar import InputBar
from src.gui.pane import RENDER_BATCH_MS, ChatPane
from src.gui.runtime import GuiPresenter


class MainWindow(QMainWindow):
    def __init__(self, presenter: GuiPresenter, bridge: UiBridge) -> None:
        QMainWindow.__init__(self)
        self.presenter = presenter
        self.bridge = bridge
        self.panes: dict[str, ChatPane] = {}
        self.active_tid: str | None = None
        self._last_input_text = ""
        self._build_ui()
        self._wire_bridge()
        # 懒建 pane（重记录重建只在首访该会话时发生，启动不预建全部）
        first = presenter.session_ids()
        self._switch_to(first[0] if first else presenter.new_session_id())

    # ---- 结构
    def _build_ui(self) -> None:
        self.setWindowTitle(f"Jarvis GUI — {self.presenter.runtime.model_label}")
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 工单 08：高级菜单（Plan/Act · YOLO · 撤回，默认收起不占主界面）
        self.mode_badge = QLabel("")
        self.mode_badge.setStyleSheet("color:#8a99a8; font-size:11px;")
        adv = self.menuBar().addMenu("高级")
        self.plan_action = adv.addAction("规划模式（Plan：写工具被拦，先规划）")
        self.plan_action.setCheckable(True)
        self.plan_action.toggled.connect(self._on_plan_toggled)
        self.yolo_action = adv.addAction("YOLO（本会话免审批）")
        self.yolo_action.setCheckable(True)
        self.yolo_action.toggled.connect(self._on_yolo_toggled)
        adv.addSeparator()
        undo_action = adv.addAction("撤回上一轮（消息层）")
        undo_action.triggered.connect(self._on_undo)
        self._advanced_menu = adv

        left = QFrame()
        left.setFixedWidth(230)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 4, 8)
        title = QLabel("<b>JARVIS</b>  会话")
        title.setStyleSheet("font-size:14px;")
        ll.addWidget(title)
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_clicked)
        self.session_list.itemDoubleClicked.connect(self._on_session_double_clicked)
        ll.addWidget(self.session_list, stretch=1)
        self.btn_new = QPushButton("＋ 新会话")
        self.btn_new.clicked.connect(lambda: self._switch_to(self.presenter.new_session_id()))
        ll.addWidget(self.btn_new)
        self.running_badge = QLabel("")
        self.running_badge.setStyleSheet("color:#ffd75e; font-size:11px;")
        ll.addWidget(self.running_badge)
        ll.addWidget(self.mode_badge)
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

        self.image_strip = ImageStrip()
        ml.addWidget(self.image_strip)
        self.input_bar = InputBar()
        self.input_bar.edit.setPlaceholderText("输入消息（Enter 发送，Shift+Enter 换行）")
        self.input_bar.set_image_paste_hook(self._try_image_paste)
        self.input_bar.submit_requested.connect(self._on_input_submit)
        self.input_bar.cancel_requested.connect(self._cancel_active)
        ml.addWidget(self.input_bar)
        root.addWidget(mid, 1)

        self.setCentralWidget(central)
        self.resize(1060, 700)

        # 150ms 合批重渲（工单 03；逐 token 即时 = pane.render_strategy="instant"）
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_BATCH_MS)
        self._render_timer.timeout.connect(self._flush_all_dirty)
        self._render_timer.start()

    # ---- 工单 08：高级模式（Plan/Act 全局 · YOLO 线程级 · 撤回消息层）
    def _on_plan_toggled(self, on: bool) -> None:
        from src import plan_mode

        plan_mode.set_mode(self.presenter.runtime.permission_state, "plan" if on else "act")
        self._refresh_mode_badges()

    def _on_yolo_toggled(self, on: bool) -> None:
        from src import permissions

        state = self.presenter.runtime.permission_state
        tid = self.active_tid or ""
        if on:
            permissions.yolo_on(state, tid)
        else:
            permissions.yolo_off(state, tid)
        self.status_label.setText(
            f"YOLO 已开启（{tid} 免审批；其他会话不受影响）" if on else "YOLO 已关闭"
        )
        self._refresh_mode_badges()

    def _on_undo(self) -> None:
        tid = self.active_tid
        if not tid:
            return
        b = self.presenter.bridge
        agent = self.presenter.runtime.agent

        def _run() -> str:
            msg = commands.undo(agent, tid)
            b.rebuild_pane.emit(tid)  # 主线程重建 pane 记录（worker 不碰 widget）
            return msg

        self.presenter.run_command(_run, tid)

    def _rebuild_pane(self, tid: str) -> None:
        p = self.panes.get(tid)
        if p is None:
            return
        from src.gui import replay

        try:
            p.rebuild_from_records(replay.thread_record(self.presenter.runtime.agent, tid))
        except Exception:  # noqa: BLE001 — 重建失败保留原 pane，不崩 app
            pass

    def _refresh_mode_badges(self) -> None:
        from src import permissions, plan_mode

        state = self.presenter.runtime.permission_state
        mode = plan_mode.current_mode(state)
        yolo = permissions.yolo_active(state, self.active_tid or "")
        bits = []
        bits.append("[Plan]" if mode == "plan" else "[Act]")
        if yolo:
            bits.append("[YOLO]")
        self.mode_badge.setText(" ".join(bits))
        # 菜单勾选态与真实状态同步（切会话后 YOLO 态随会话变）
        self.yolo_action.blockSignals(True)
        self.yolo_action.setChecked(yolo)
        self.yolo_action.blockSignals(False)

    # ---- 会话栈
    def _ensure_pane(self, tid: str) -> ChatPane:
        if tid in self.panes:
            return self.panes[tid]
        p = ChatPane(tid)
        # 工单 06：冷建/首访旧会话 → 检查点完整记录重建（含工具行，默认折叠）
        from src.gui import replay

        try:
            p.rebuild_from_records(replay.thread_record(self.presenter.runtime.agent, tid))
        except Exception:  # noqa: BLE001 — 记录重建是增强，失败回落空 pane 不崩
            pass
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
        self.input_bar.edit.setFocus()
        note = "（回合进行中，切走不影响执行）" if self.presenter.gate.is_running(tid) else ""
        self.status_label.setText(f"会话 {tid}{note}")
        self._refresh_mode_badges()

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
            label = self.presenter.session_label(tid)
            mark = "▸ " if tid == self.active_tid else "   "
            run = " ⚡" if self.presenter.gate.is_running(tid) else ""
            it = QListWidgetItem(f"{mark}{label}{run}")
            it.setData(Qt.UserRole, tid)
            it.setToolTip(tid)
            self.session_list.addItem(it)
            if tid == self.active_tid:
                self.session_list.setCurrentItem(it)

    # ---- 会话改名（工单 05：双击改名即时生效 + 持久化）
    def _on_session_double_clicked(self, item: QListWidgetItem) -> None:
        from PySide6.QtWidgets import QInputDialog

        tid = item.data(Qt.UserRole)
        new_title, okk = QInputDialog.getText(self, "重命名会话", "新名称:", text=item.text().lstrip("▸ ").rstrip())
        if okk and new_title.strip():
            self.presenter.rename_session(tid, new_title.strip())
            self.refresh_sessions()

    # ---- 图片粘贴（工单 07）：剪贴板图 / 图片路径 → 附件条
    def _try_image_paste(self) -> bool:
        from PySide6.QtWidgets import QApplication

        cb = QApplication.clipboard()
        img = cb.image()
        if img is not None and not img.isNull():
            path = save_clipboard_image_to_temp(img)
            if path:
                self.image_strip.add_image(path)
                self.status_label.setText("已添加图片附件（发送前可 ✕ 移除）")
                return True
        p = clipboard_image.looks_like_image_path(cb.text() or "")
        if p:
            self.image_strip.add_image(p)
            self.status_label.setText("已添加图片附件")
            return True
        return False  # 普通文本走原生粘贴

    # ---- 发送 / 回合
    def _submit(self) -> None:
        # InputBar 已清空编辑框并 emit 原始多行文本（含换行，走 build_submission）
        raw = self._last_input_text
        payload, note = commands.build_submission(
            raw, tuple(commands.virtual_path_mappings(self.presenter.runtime.config))
        )
        if note:
            self.status_label.setText(note)
            return
        if payload is None:
            return
        images = self.image_strip.paths()
        user_input, user_input_fallback, _ = build_image_submit(payload, images)
        tid = self.active_tid
        p = self._ensure_pane(tid)
        p.append_user(payload, images or None)
        if images:
            self.image_strip.clear()
        verdict = self.presenter.start_turn(
            tid, payload, user_input=user_input, user_input_fallback=user_input_fallback
        )
        self.input_bar.set_cancel_enabled(verdict == "started")
        self.status_label.setText(
            "已发送，执行中…" if verdict == "started" else "已排队，回合结束后自动续发"
        )

    def _on_input_submit(self, raw: str) -> None:
        self._last_input_text = raw
        self._submit()

    def _cancel_active(self) -> None:
        if self.active_tid:
            self.presenter.cancel(self.active_tid)

    def _flush_all_dirty(self) -> None:
        for p in self.panes.values():
            p.flush_dirty()

    # ---- 桥接（worker → 主线程渲染）
    def _wire_bridge(self) -> None:
        b = self.bridge
        b.message_delta.connect(self._on_delta)
        b.message_end.connect(self._on_msg_end)
        b.fallback.connect(self._on_fallback)
        b.tool_call.connect(self._on_tool)
        b.subagent.connect(self._on_subagent)
        b.thinking.connect(self._on_thinking)
        b.status.connect(self._on_status)
        b.turn_started.connect(self._on_turn_started)
        b.turn_done.connect(self._on_turn_done)
        b.refresh_sessions.connect(self.refresh_sessions)
        b.notify.connect(self._on_notify)
        b.create_card.connect(self._on_create_card)
        b.focus_input.connect(self._on_focus_input)
        b.rebuild_pane.connect(self._rebuild_pane)

    def _on_create_card(self, tid: str, payload, card_id: str) -> None:
        from src.gui.cards import card_widget_from_payload

        p = self.panes.get(tid)
        if p is None:
            p = self._ensure_pane(tid)
        p.append_card(card_widget_from_payload(payload))

    def _on_focus_input(self) -> None:
        self.input_bar.edit.setFocus()

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

    def _on_thinking(self, tid: str, delta: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.thinking_delta(delta)

    def _on_status(self, tid: str, text: str) -> None:
        if tid == self.active_tid:
            self.status_label.setText(text)

    def _on_turn_started(self, tid: str) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.running = True
        self.input_bar.set_cancel_enabled(True)
        self.refresh_sessions()

    def _on_turn_done(self, tid: str, ok: bool) -> None:
        p = self.panes.get(tid)
        if p is not None:
            p.running = self.presenter.gate.is_running(tid)
        self.input_bar.set_cancel_enabled(bool(self.presenter.gate.running_threads()))
        self.refresh_sessions()

    def _on_notify(self, text: str) -> None:
        self.status_label.setText(text)
