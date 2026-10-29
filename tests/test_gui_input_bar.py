"""工单 03 → 2026-10-28 — 输入区：固定 5 行高（旧 1 行拉高 5 倍）+ 超出走右侧
垂直滚动条（滚轴/拖动，Qt 原生）+ 提交语义 + 队列提示（offscreen）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.input_bar import InputBar, compute_input_height  # noqa: E402


# ---- 纯函数：固定 5 行高（不再随内容行数增长）
def test_compute_input_height_fixed_five_lines():
    assert compute_input_height(20) == 5 * 20 + 4
    assert compute_input_height(16) == 5 * 16 + 4
    # 自定义行数（如将来要调规格）
    assert compute_input_height(20, lines=3) == 3 * 20 + 4


def test_input_bar_height_fixed_regardless_of_content(qtbot):
    """规格核心：无论内容几行，输入框恒为 5 行高（旧版「1→5 自动拉高」作废）。"""
    bar = InputBar()
    qtbot.addWidget(bar)
    bar.show()
    fm = bar.edit.fontMetrics()
    h0 = bar.edit.height()
    assert h0 == compute_input_height(fm.height())
    bar.edit.setPlainText("第一行\n第二行\n第三行")
    bar._refit()
    assert bar.edit.height() == h0  # 3 行内容不改变框高


def test_input_bar_overflow_gets_scrollbar_range(qtbot):
    """内容超出 5 行：垂直滚动条按需出现（滚轴滚动 + 拖动 thumb = Qt 原生）；
    以滚动条行程 > 0 为确定性判据（offscreen 下可见性不可靠）。"""
    bar = InputBar()
    qtbot.addWidget(bar)
    bar.show()
    bar.edit.setPlainText("\n".join(f"line{i}" for i in range(9)))
    bar._refit()
    sb = bar.edit.verticalScrollBar()
    assert sb.maximum() > 0, "9 行内容应产生滚动行程"
    assert bar.edit.horizontalScrollBar().maximum() == 0  # 横向滚动条常关


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
