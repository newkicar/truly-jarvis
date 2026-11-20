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


def test_shift_enter_consumed_and_inserts_newline(qtbot):
    """Shift+Enter：eventFilter 消费事件并显式插入 \n（不再依赖原生——确定性优先）。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from PySide6.QtGui import QTextCursor

    bar = InputBar(); qtbot.addWidget(bar)
    bar.edit.setPlainText("a")
    bar.edit.moveCursor(QTextCursor.MoveOperation.End)  # 模拟用户停在末尾（setPlainText 会重置光标到 0）
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Return, Qt.ShiftModifier)
    assert bar.eventFilter(bar.edit, ev)  # 消费（显式插入换行）
    assert bar.edit.toPlainText() == "a\n"


def test_alt_enter_consumed_and_inserts_newline(qtbot):
    """Alt+Enter 与 Shift+Enter 同义：消费事件并显式插入 \n，不提交。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from PySide6.QtGui import QTextCursor

    bar = InputBar(); qtbot.addWidget(bar)
    submitted: list[str] = []
    bar.submit_requested.connect(submitted.append)
    bar.edit.setPlainText("a")
    bar.edit.moveCursor(QTextCursor.MoveOperation.End)  # 模拟用户停在末尾（setPlainText 会重置光标到 0）
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_Return, Qt.AltModifier)
    assert bar.eventFilter(bar.edit, ev)  # 消费（显式插入换行）
    assert bar.edit.toPlainText() == "a\n"
    assert submitted == []


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

def test_fill_text_backfills_only_when_empty(qtbot):
    """gui-ux16 undo 回填：仅空框写入（不覆盖进行中草稿），光标置于末尾；空串 no-op。"""
    bar = InputBar()
    qtbot.addWidget(bar)
    bar.show()
    # 空框 → 写入且光标到末尾
    bar.fill_text("这个人叫什么")
    assert bar.edit.toPlainText() == "这个人叫什么"
    assert bar.edit.textCursor().position() == len("这个人叫什么")
    # 有草稿 → 拒写（保留用户正在编辑的内容）
    bar.fill_text("新草稿")
    assert bar.edit.toPlainText() == "这个人叫什么"
    # 空串 → no-op
    bar.fill_text("")
    assert bar.edit.toPlainText() == "这个人叫什么"


def test_shift_enter_inserts_newline(qtbot):
    """行为级固化：Shift+Enter 在输入框真插入换行且不误提交。"""
    from PySide6.QtCore import Qt

    bar = InputBar(); qtbot.addWidget(bar)
    bar.show()
    submitted: list[str] = []
    bar.submit_requested.connect(submitted.append)
    bar.edit.setPlainText("abc")
    bar.edit.setFocus()
    qtbot.keyClick(bar.edit, Qt.Key_Return, Qt.ShiftModifier)
    qtbot.keyClick(bar.edit, Qt.Key_X)
    assert "\n" in bar.edit.toPlainText()
    assert submitted == []


def test_alt_enter_inserts_newline(qtbot):
    """行为级：Alt+Enter 与 Shift+Enter 同义——真插入换行、不误提交（用户实测 GUI 无反应的红灯）。"""
    from PySide6.QtCore import Qt

    bar = InputBar(); qtbot.addWidget(bar)
    bar.show()
    submitted: list[str] = []
    bar.submit_requested.connect(submitted.append)
    bar.edit.setPlainText("abc")
    bar.edit.setFocus()
    qtbot.keyClick(bar.edit, Qt.Key_Return, Qt.AltModifier)
    qtbot.keyClick(bar.edit, Qt.Key_X)
    assert "\n" in bar.edit.toPlainText(), "Alt+Enter 应插入换行"
    assert submitted == [], "Alt+Enter 不得提交"
