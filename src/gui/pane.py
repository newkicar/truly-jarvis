"""每 thread 独立消息栈聊天面板（QScrollArea + 粘底跟随状态机）。

切会话 = 换栈不重建 runtime（每个 thread 一个 ChatPane 实例常驻 QStackedWidget）。
粘底跟随平移 tui-ux16r2 的 stick 状态机：贴底=跟随，上翻=停跟随 + 显「回到底部」pill，
点 pill 或滚回底部恢复跟随。兄弟 resize 不拽底（只在上翻态清 pending）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui import md_render


class ChatPane(QScrollArea):
    """单个会话的消息面板。owner 负责流事件 → append_* 的映射。"""

    def __init__(self, tid: str, parent=None) -> None:
        super().__init__(parent)
        self.tid = tid
        self.stick = True
        self.running = False
        self._ai_label: QLabel | None = None
        self._ai_buf = ""
        self._back_btn: QPushButton | None = None

        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self._vbox = QVBoxLayout(inner)
        self._vbox.setContentsMargins(10, 10, 10, 10)
        self._vbox.setSpacing(6)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vbox.addWidget(spacer, stretch=1)
        self.setWidget(inner)

        # 悬浮「回到底部」pill（工单 03 正式化；01 先内置同一状态机）
        pill_host = QWidget(inner)
        pl = QHBoxLayout(pill_host)
        pl.setContentsMargins(0, 0, 8, 8)
        pl.addStretch(1)
        self._back_btn = QPushButton("↓ 回到底部")
        self._back_btn.setVisible(False)
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border-radius:10px;"
            " padding:2px 10px; } QPushButton:hover { background:#1976d2; }"
        )
        self._back_btn.clicked.connect(self.snap_to_bottom)
        pl.addWidget(self._back_btn)
        self._vbox.addWidget(pill_host)

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ---- 块追加
    def _insert(self, w: QWidget) -> None:
        # 插到 spacer 之前（保持 spacer 永远在底部 stretch）
        self._vbox.insertWidget(self._vbox.count() - 1, w)

    def append_user(self, text: str) -> None:
        l = QLabel(f"[你] {text}")
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setTextFormat(Qt.PlainText)
        l.setStyleSheet("color:#e8e8e8; background:#1f3a5f; border-radius:4px; padding:6px;")
        self._insert(l)
        self._follow()

    def append_thinking(self, text: str) -> None:
        """思考块（工单 06；小字淡色）。"""
        l = QLabel(md_render.thinking_block_html(text))
        l.setTextFormat(Qt.RichText)
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setStyleSheet("background:#0d1117; border-radius:4px; padding:4px;")
        self._insert(l)
        self._follow()

    def append_fallback(self, text: str) -> None:
        if not text:
            return
        l = QLabel(md_render.md_to_qt_html(text))
        l.setTextFormat(Qt.RichText)
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setStyleSheet("background:#101820; border-radius:4px; padding:6px;")
        self._insert(l)
        self._follow()

    def append_tool(self, name, args, err, output, depth=0) -> None:
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
        l.setFont(md_render.mono_font())
        l.setStyleSheet(f"color:{color}; font-size:12px;")
        self._insert(l)
        self._follow()

    def append_subagent(self, name, status, depth=0) -> None:
        l = QLabel(f"{'  ' * depth}[{name}] {status}")
        l.setTextInteractionFlags(Qt.TextSelectableByMouse)
        l.setStyleSheet("color:#ffd75e; font-size:12px;")
        self._insert(l)
        self._follow()

    # ---- 流式 AI 消息
    def ai_delta(self, delta: str) -> None:
        self._ai_buf += delta
        if self._ai_label is None:
            self._ai_label = QLabel()
            self._ai_label.setTextFormat(Qt.RichText)
            self._ai_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._ai_label.setWordWrap(True)
            self._ai_label.setStyleSheet("background:#101820; border-radius:4px; padding:6px;")
            self._insert(self._ai_label)
        self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf))
        self._follow()

    def ai_end(self, text: str) -> None:
        if self._ai_label is not None:
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf or text))
            self._ai_label = None
            self._ai_buf = ""
        elif text:
            self.append_fallback(text)
        self._follow()

    def append_card(self, card: QWidget) -> None:
        self._insert(card)
        self._follow()

    # ---- 粘底状态机
    def _at_bottom(self, tol: int = 4) -> bool:
        sb = self.verticalScrollBar()
        return sb.value() >= sb.maximum() - tol

    def _follow(self) -> None:
        if self.stick:
            self.snap_to_bottom()

    def snap_to_bottom(self) -> None:
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.stick = True
        if self._back_btn is not None:
            self._back_btn.setVisible(False)

    def _on_scroll(self, _v: int) -> None:
        if self._at_bottom():
            self.stick = True
            if self._back_btn is not None:
                self._back_btn.setVisible(False)
        else:
            self.stick = False
            if self._back_btn is not None:
                self._back_btn.setVisible(True)

    def rebuild_from_history(self, history: list[tuple[str, str]]) -> None:
        """冷启动从检查点重建文本消息（user/ai）；工具行重建见工单 06。"""
        for role, text in history:
            if role == "user":
                self.append_user(text)
            elif role == "ai":
                self.append_fallback(text)
        self.stick = True
        self.snap_to_bottom()
