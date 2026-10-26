"""每 thread 独立消息栈聊天面板（QScrollArea + 粘底跟随状态机）。

切会话 = 换栈不重建 runtime（每个 thread 一个 ChatPane 实例常驻 QStackedWidget）。
工单 03 过稿形状：
- 粘底状态机（stick）：贴底=跟随，上翻=停跟随；悬浮「↓」小圆钮（贴聊天区右下角、
  不占布局行）上翻显/到底隐，点击=跳底恢复跟随（tui-ux16r2 平移）。
- 流式 Markdown 合批重渲（150ms，owner 的 QTimer 驱动 flush_dirty）；逐 token 即时
  策略开关 render_strategy="instant"。
- PgUp/PgDn/Home/End 四键 + 点击聚焦（工单 03/06 联动 stick）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui import md_render

RENDER_BATCH_MS = 150


class ChatPane(QScrollArea):
    """单个会话的消息面板。owner 负责流事件 → append_* 的映射。"""

    def __init__(self, tid: str, parent=None) -> None:
        super().__init__(parent)
        self.tid = tid
        self.stick = True
        self.running = False
        self.render_strategy = "batch"
        self._ai_label: QLabel | None = None
        self._ai_buf = ""
        self._dirty = False
        self._back_btn: QPushButton | None = None

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 点击聚焦（四键前提）
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self._vbox = QVBoxLayout(inner)
        self._vbox.setContentsMargins(10, 10, 10, 10)
        self._vbox.setSpacing(6)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vbox.addWidget(spacer, stretch=1)
        self.setWidget(inner)

        # 悬浮「↓」pill：viewport 子部件（滚动不带走），贴右下角、不占布局行
        self._back_btn = QPushButton("↓")
        self._back_btn.setFixedSize(34, 34)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setText("↓")
        self._back_btn.setToolTip("回到底部")
        self._back_btn.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border-radius:17px;"
            " font-size:16px; font-weight:bold; } QPushButton:hover { background:#1976d2; }"
        )
        self._back_btn.clicked.connect(self.snap_to_bottom)
        self._back_btn.setParent(self.viewport())
        self._back_btn.setVisible(False)
        self._reposition_pill()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    # ---- 块追加
    def _insert(self, w: QWidget) -> None:
        # 插到 spacer 之前（保持 spacer 永远在底部 stretch）
        self._vbox.insertWidget(self._vbox.count() - 1, w)

    def append_user(self, text: str) -> None:
        l = QLabel(f"[你] {text}")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setTextFormat(Qt.TextFormat.PlainText)
        l.setStyleSheet("color:#e8e8e8; background:#1f3a5f; border-radius:4px; padding:6px;")
        self._insert(l)
        self._follow()

    def append_thinking(self, text: str) -> None:
        """思考块（工单 06；小字淡色）。"""
        l = QLabel(md_render.thinking_block_html(text))
        l.setTextFormat(Qt.TextFormat.RichText)
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setStyleSheet("background:#0d1117; border-radius:4px; padding:4px;")
        self._insert(l)
        self._follow()

    def append_fallback(self, text: str) -> None:
        if not text:
            return
        l = QLabel(md_render.md_to_qt_html(text))
        l.setTextFormat(Qt.TextFormat.RichText)
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
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
        l.setTextFormat(Qt.TextFormat.PlainText)
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setFont(md_render.mono_font())
        l.setStyleSheet(f"color:{color}; font-size:12px;")
        self._insert(l)
        self._follow()

    def append_subagent(self, name, status, depth=0) -> None:
        l = QLabel(f"{'  ' * depth}[{name}] {status}")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setStyleSheet("color:#ffd75e; font-size:12px;")
        self._insert(l)
        self._follow()

    # ---- 流式 AI 消息（合批 / 即时双策略）
    def ai_delta(self, delta: str) -> None:
        self._ai_buf += delta
        if self._ai_label is None:
            self._ai_label = QLabel()
            self._ai_label.setTextFormat(Qt.TextFormat.RichText)
            self._ai_label.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
            self._ai_label.setWordWrap(True)
            self._ai_label.setStyleSheet("background:#101820; border-radius:4px; padding:6px;")
            self._insert(self._ai_label)
        if self.render_strategy == "instant":
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf))
            self._dirty = False
            self._follow()
        else:
            self._dirty = True  # 150ms 合批由 owner 的 QTimer 驱动 flush_dirty

    def flush_dirty(self) -> None:
        """合批渲染：owner 的 RENDER_BATCH_MS 定时器调用。"""
        if self._dirty and self._ai_label is not None:
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf))
            self._dirty = False
            self._follow()

    def ai_end(self, text: str) -> None:
        if self._ai_label is not None:
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf or text))
            self._ai_label = None
            self._ai_buf = ""
            self._dirty = False
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
        self._set_pill(False)

    def _on_scroll(self, _v: int) -> None:
        bottom = self._at_bottom()
        self.stick = bottom
        self._set_pill(not bottom)

    def _set_pill(self, visible: bool) -> None:
        if self._back_btn is not None:
            self._back_btn.setVisible(visible)

    def _reposition_pill(self) -> None:
        if self._back_btn is None:
            return
        vp = self.viewport()
        self._back_btn.move(vp.width() - 44, vp.height() - 44)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_pill()

    # ---- 四键滚动 + 点击聚焦（工单 03）
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        sb = self.verticalScrollBar()
        page = max(1, self.viewport().height())
        if event.key() == Qt.Key_PageUp:
            sb.setValue(sb.value() - page)
            self._on_scroll(sb.value())
            return
        if event.key() == Qt.Key_PageDown:
            sb.setValue(sb.value() + page)
            self._on_scroll(sb.value())
            return
        if event.key() == Qt.Key_Home:
            sb.setValue(0)
            self._on_scroll(0)
            return
        if event.key() == Qt.Key_End:
            self.snap_to_bottom()
            return
        super().keyPressEvent(event)

    def rebuild_from_history(self, history: list[tuple[str, str]]) -> None:
        """冷启动从检查点重建文本消息（user/ai）；工具行重建见工单 06。"""
        for role, text in history:
            if role == "user":
                self.append_user(text)
            elif role == "ai":
                self.append_fallback(text)
        self.stick = True
        self.snap_to_bottom()
