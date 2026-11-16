"""GUI 状态栏 StatusView：可复制 + 自动换行（替代旧 QLabel 状态栏）。

两个旧毛病：
- QLabel 不支持选区复制 → 命令执行输出（/history、失败堆栈等）看得见却拷不走；
- 多行被压平成单行 → 长文本横向顶爆窗口宽度。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QWidget

from src.gui.status_view import MAX_LINES, PAD, StatusView


def test_status_view_contract(qapp):
    w = StatusView("hello")
    assert isinstance(w, QPlainTextEdit)
    assert w.objectName() == "status-bar"
    assert w.isReadOnly()
    assert w.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    assert w.text() == "hello"
    w.setText("new text")
    assert w.text() == "new text"


def test_status_view_selectable_copy(qapp):
    text = "line1\nline2\nline3"
    w = StatusView(text)
    w.show()
    w.selectAll()
    w.copy()
    qapp.processEvents()
    assert qapp.clipboard().text() == text


def test_status_view_height_one_line(qapp):
    w = StatusView("只有一行")
    assert w.height() == w.fontMetrics().lineSpacing() + PAD


def test_status_view_height_capped(qapp):
    text = "\n".join("第 %d 行" % i for i in range(1, 21))
    w = StatusView(text)
    assert w.height() == MAX_LINES * w.fontMetrics().lineSpacing() + PAD
    # 高度封顶但全文仍在（内部垂直滚动可读）
    assert w.toPlainText() == text


def test_status_view_follows_parent_width(qapp):
    host = QWidget()
    layout = QHBoxLayout(host)
    w = StatusView("长" * 200)
    layout.addWidget(w)
    host.resize(300, 200)
    host.show()
    qapp.processEvents()
    # 自动换行：内容再长也不把窗口撑宽（宽度由父布局决定）
    assert w.width() <= 300
