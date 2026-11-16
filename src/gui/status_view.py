"""状态栏 widget（StatusView）：可复制 + 自动换行的多行状态显示。

替代旧 QLabel 状态栏（两个旧毛病）：
- QLabel 不支持选区复制 → 命令输出（/history、失败堆栈等）读出来却无法拷贝；
- 多行文本被压平成单行 → 长文本横向顶爆窗口宽度。

行为：
- QPlainTextEdit 只读：可拖选/全选/复制（ctrl+c、右键复制）；
- WidgetWidth 自动换行：宽度由父布局决定，内容不再撑宽窗口；
- 自适应高度：1~MAX_LINES 行随内容，超出上限内部滚动（竖滚按需）。

对外保持 QLabel 的 setText(str) / text() 契约不变，
main_window 约 30 处 status_label 调用点与既有测试断言零改动。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit

# 显示上限：最多 4 行，超出走内部垂直滚动（widget 高度封顶，不随内容无限长）
MAX_LINES = 4
# 高度余量：CSS padding 2px x 2（theme.py QPlainTextEdit#status-bar）
# + QPlainTextEdit 文档默认 margin 4px x 2，留到 12 避免首末行被裁
PAD = 12


class StatusView(QPlainTextEdit):
    """多行可复制状态栏。接口与 QLabel 的 setText/text 兼容。"""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("status-bar")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 点击即可选区复制；Tab 不抢焦（避免从输入框 Tab 进状态栏）
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setTabChangesFocus(False)
        self.setPlainText(text)
        self._fit_height(text)

    # ---- QLabel 兼容接口（约 30 处调用点与既有测试只依赖这两个方法）----
    def setText(self, text: str) -> None:  # noqa: N802 - QLabel 契约
        self.setPlainText(text)
        self._fit_height(text)

    def text(self) -> str:  # noqa: N802 - QLabel 契约
        return self.toPlainText()

    # ---- 内部 ----
    def _fit_height(self, text: str) -> None:
        """高度 = min(物理行数, MAX_LINES) x 行高 + PAD；超限内容内部滚动。

        物理行数（按换行符计）与窗口宽度无关，布局重排/换行不引起高度抖动，
        offscreen 下也确定性可测。宽度变化时若换行使显示行数超过上限，
        超出部分由内部竖滚承接，widget 自身高度仍封顶。
        """
        lines = len(text.splitlines()) or 1
        n = max(1, min(lines, MAX_LINES))
        self.setFixedHeight(n * self.fontMetrics().lineSpacing() + PAD)

    def resizeEvent(self, event) -> None:
        # 父布局重排后重算一次（当前实现与宽度无关，保险钩子）
        super().resizeEvent(event)
        self._fit_height(self.toPlainText())