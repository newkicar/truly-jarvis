"""待发队列条（gui15 G5）：排队中的消息固定在输入框上方，不随对话窗滚动。
核心语义：用户气泡仅在回合真正开跑时进对话窗；排队期间渲染在本条内
（#1..#N 行，多行压平单行 + tooltip 全文 + 可选中），每行带「撤出」按钮——
点一下退出队列、原文写回输入框（TurnGate.pull_out）。
set_items 每次整体重建；纯数据 list[str]，主线程驱动，无 agent/Qt 事件循环依赖。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class _WrapLabel(QLabel):
    """wordwrap 队列行标签：minimumSizeHint 宽度钳制（#3，pane.py CapLabel 先例 L32-43）——
    wordwrap 标签不钳制时，最长不可断片段宽度经布局传播把窗口撑宽；钳 48px 后
    文字在窗口宽度内折行，窗口宽度不再随内容。（Qt 先例：LabelWordWrapWide。）"""

    def minimumSizeHint(self):  # noqa: N802
        base = super().minimumSizeHint()
        return QSize(min(base.width(), 48), base.height())


class QueueStrip(QWidget):
    """输入框上方待发队列条：有排队消息才显示；每行「插队」→ jump_requested(原文)
    （立即注入当前回合，对标 codex queued-chip Steer），「撤出」→ pull_out_requested(原文)。"""

    pull_out_requested = Signal(str)
    jump_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("queue-strip")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(4, 2, 4, 2)
        self._lay.setSpacing(2)
        self._rows: list[QWidget] = []
        self._items: list[str] = []
        self.hide()

    def set_items(self, items: list[str]) -> None:
        for r in self._rows:
            r.setParent(None)
            r.deleteLater()
        self._rows = []
        self._items = list(items)
        for i, text in enumerate(self._items, start=1):
            row = QWidget(self)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            label = _WrapLabel(f"#{i} " + text.replace("\n", " "), row)
            label.setObjectName("queue-chip")
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setToolTip(text)
            rl.addWidget(label, 1)
            jb = QPushButton("插队", row)
            jb.setObjectName("btn-ghost")
            jb.setFixedHeight(20)
            jb.setToolTip("立即插队：不等本轮结束，注入当前回合的下一步模型调用")
            jb.clicked.connect(lambda _=False, t=text: self.jump_requested.emit(t))
            rl.addWidget(jb)
            btn = QPushButton("撤出", row)
            btn.setObjectName("btn-ghost")
            btn.setFixedHeight(20)
            btn.setToolTip("撤出队列，返回输入框（原文保留）")
            btn.clicked.connect(lambda _=False, t=text: self.pull_out_requested.emit(t))
            rl.addWidget(btn)
            self._rows.append(row)
            self._lay.addWidget(row)
        self.setVisible(bool(self._items))

    def items(self) -> list[str]:
        return list(self._items)
