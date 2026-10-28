"""工单 03 — 输入区：1→5 行自动拉高（纯函数）+ 提交语义 + 队列提示（offscreen）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.input_bar import InputBar, compute_input_height  # noqa: E402


# ---- 纯函数：高度自适应（1..5 行截断）
def test_compute_input_height_caps_at_five_lines():
    assert compute_input_height(1, 20) == 1 * 20 + 4
    assert compute_input_height(3, 20) == 3 * 20 + 4
    assert compute_input_height(9, 20) == 5 * 20 + 4  # 截断到 5 行，超限内滚


def test_compute_input_height_min_one():
    assert compute_input_height(0, 20) == 1 * 20 + 4


def test_input_bar_grows_with_lines(qtbot):
    bar = InputBar(); qtbot.addWidget(bar)
    h1 = bar.edit.height()
    bar.edit.setPlainText("第一行\n第二行\n第三行")
    bar._refit()
    assert bar.edit.height() > h1


def test_input_bar_caps_at_five_lines(qtbot):
    bar = InputBar(); qtbot.addWidget(bar)
    bar.edit.setPlainText("\n".join(f"line{i}" for i in range(9)))
    bar._refit()
    fm = bar.edit.fontMetrics()
    assert bar.edit.height() == compute_input_height(5, fm.height())


def test_enter_submits_and_clears(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    bar = InputBar(); qtbot.addWidget(bar)
    submitted: list[str] = []
    bar.submit_requested.connect(submitted.append)
    bar.edit.setPlainText("多行\n消息")
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Return, Qt.NoModifier)
    assert bar.eventFilter(bar.edit, ev)  # 拦截
    assert submitted == ["多行\n消息"]
    assert bar.edit.toPlainText() == ""


def test_shift_enter_not_intercepted(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    bar = InputBar(); qtbot.addWidget(bar)
    bar.edit.setPlainText("a")
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Return, Qt.ShiftModifier)
    assert not bar.eventFilter(bar.edit, ev)  # 放行（换行交 QPlainTextEdit 原生处理）


def test_input_bar_single_layout_no_double_set(qtbot):
    """回归（2026-10-28）：__init__ 曾对 InputBar 两次 setLayout（QHBoxLayout(self)×2）
    → Qt 告警 'Attempting to add QLayout ... which already has a layout'，且布局崩坏
    输入条塌成 0 高不可见。单一布局后：控件有父布局 + 行高 > 0。"""
    bar = InputBar()
    qtbot.addWidget(bar)
    assert bar.layout() is not None
    assert bar.edit.parentWidget() is bar
    assert bar.btn_send.parentWidget() is bar
    bar.show()
    assert bar.sizeHint().height() > 0
