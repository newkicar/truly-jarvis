"""输入区组件（工单 03 → 2026-10-28 规格更新）：固定 5 行高（旧 1 行基线拉高 5 倍）
+ 内容超 5 行时右侧垂直滚动条（鼠标滚轴 + 拖动 thumb，QPlainTextEdit 原生）。

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

# 输入框固定高度 = 5 行（用户裁定：旧 1 行太矮「连一行完整的字都看不见」，拉高 5 倍；
# 超出 5 行不继续长框，改用右侧滚动条：滚轴上下滚 + 按住滚动条拖动，均 Qt 原生）
FIXED_LINES = 5


def compute_input_height(line_h: int, top_pad: int = 4, lines: int = FIXED_LINES) -> int:
    """输入框固定高度 = lines × 行高 + 上下边距（不再随内容行数增长）。纯函数，TDD。"""
    return max(1, lines) * line_h + top_pad


class InputBar(QWidget):
    """多行输入 + 发送/取消按钮。submit_requested 携带原始文本（含换行）。"""

    submit_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._image_paste_hook: "Callable[[], bool] | None" = None
        self.edit = QPlainTextEdit()
        self.edit.setTabChangesFocus(True)
        # 内容超出固定 5 行高度时：右侧垂直滚动条按需出现（滚轴上下滚 + 按住拖动，
        # QPlainTextEdit 原生行为；AsNeeded 为缺省但显式声明意图）
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self._refit()

    # ---- 高度（固定 5 行；内容超出走垂直滚动条，框不再增长）
    def _refit(self) -> None:
        fm = self.edit.fontMetrics()
        self.edit.setFixedHeight(compute_input_height(fm.height()))

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
