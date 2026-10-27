"""输入区组件（工单 03）：1→5 行自动拉高 + 超限内滚 + Enter/Shift+Enter 提交语义。

Ctrl+C/V/X/A 走 Qt 原生（选中文本即复制，事件过滤焦点归还，不劫持）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

MIN_LINES = 1
MAX_LINES = 5


def compute_input_height(doc_lines: int, line_h: int, top_pad: int = 4) -> int:
    """输入框高度 = 行数（1..5 截断）× 行高 + 上下边距。纯函数，TDD。"""
    n = max(MIN_LINES, min(doc_lines, MAX_LINES))
    return n * line_h + top_pad


class InputBar(QWidget):
    """多行输入 + 发送/取消按钮。submit_requested 携带原始文本（含换行）。"""

    submit_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_paste_hook: "Callable[[], bool] | None" = None
        self.edit = QPlainTextEdit()
        self.edit.setTabChangesFocus(True)
        self.edit.textChanged.connect(self._refit)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        self.btn_send = QPushButton("发送")
        self.btn_send.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold;"
            " border-radius:4px; padding:2px 12px; }"
        )
        self.btn_send.clicked.connect(self._submit)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, stretch=1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_send)

        self.edit.installEventFilter(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.edit, stretch=1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_send)

        self._refit()

    # ---- 高度自适应（1→5 行，超限内滚）
    def _refit(self) -> None:
        lines = max(1, self.edit.document().blockCount())
        fm = self.edit.fontMetrics()
        self.edit.setFixedHeight(compute_input_height(lines, fm.height()))

    def set_image_paste_hook(self, hook) -> None:
        """Ctrl+V 时先调 hook()：True=已按图片/路径入附件条（消费），False=走原生粘贴。"""
        self._image_paste_hook = hook

    # ---- 键位（事件过滤）：裸 Enter/Return=提交整框；Shift+Enter=框内换行（原生）。
    #      Ctrl+C/V/X/A 等修饰组合不拦截，走 Qt 原生（选区复制保留）。
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        from PySide6.QtGui import QKeyEvent

        if obj is self.edit and isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    return False  # 换行走原生
                self._submit()
                return True
            if key == Qt.Key_V and (event.modifiers() & Qt.ControlModifier):
                if self._image_paste_hook is not None and self._image_paste_hook():
                    return True  # 图片/路径已入附件条
        return super().eventFilter(obj, event)

    def _submit(self) -> None:
        text = self.edit.toPlainText()
        if text.strip():
            self.submit_requested.emit(text)
            self.edit.clear()
            self._refit()

    def set_cancel_enabled(self, enabled: bool) -> None:
        self.btn_cancel.setEnabled(enabled)
