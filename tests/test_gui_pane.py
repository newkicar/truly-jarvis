"""工单 03 — 对话区渲染层：粘底状态机 + 悬浮 pill + 四键 + 合批渲染（offscreen）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.pane import ChatPane  # noqa: E402


def test_stick_follows_when_at_bottom(qtbot):
    p = ChatPane("t1"); qtbot.addWidget(p)
    p.append_user("hello")
    p.snap_to_bottom()
    assert p.stick is True
    assert not p._back_btn.isVisible()


def _pane_with_overflow(qtbot, qapp, lines: int = 40):
    """offscreen 不传播尺寸 → 直接给滚动条设 range 制造「溢出态」，测粘底状态机。"""
    p = ChatPane("t1")
    qtbot.addWidget(p)
    p.show()
    for i in range(lines):
        p.append_user(f"line {i}")
    p.verticalScrollBar().setRange(0, 1000)  # 制造可滚动区间（不依赖真实布局）
    return p


def test_scroll_up_stops_follow_and_shows_pill(qtbot, qapp):
    p = _pane_with_overflow(qtbot, qapp)
    p.snap_to_bottom()
    sb = p.verticalScrollBar()
    sb.setValue(0)  # 上翻到顶
    p._on_scroll(0)
    assert p.stick is False
    assert p._back_btn.isVisible()  # 悬浮 pill 出现


def test_back_to_bottom_restores_stick_and_hides_pill(qtbot, qapp):
    p = _pane_with_overflow(qtbot, qapp)
    p.snap_to_bottom()
    p.verticalScrollBar().setValue(0)
    p._on_scroll(0)
    assert p._back_btn.isVisible()
    p._back_btn.click()
    assert p.stick is True
    assert not p._back_btn.isVisible()
    assert p.verticalScrollBar().value() == p.verticalScrollBar().maximum()


def test_four_keys(qtbot, qapp):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import Qt

    p = _pane_with_overflow(qtbot, qapp)
    sb = p.verticalScrollBar()
    p.snap_to_bottom()

    def press(key):
        ev = QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.NoModifier)
        p.keyPressEvent(ev)

    press(Qt.Key_Home)
    assert sb.value() == 0 and p.stick is False
    press(Qt.Key_End)
    assert sb.value() == sb.maximum() and p.stick is True
    press(Qt.Key_PageUp)
    assert p.stick is False
    press(Qt.Key_PageDown)
    assert sb.value() == sb.maximum()
    p.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key_End, Qt.NoModifier))
    assert p.stick is True


def test_batch_render_accumulates_until_flush(qtbot):
    p = ChatPane("t1"); qtbot.addWidget(p)
    p.render_strategy = "batch"
    p.ai_delta("## 标题\n")
    p.ai_delta("正文部分")
    # 合批：未 flush 前 label 内容为空（等待 150ms 定时器）
    assert p._ai_label.text() == ""
    p.flush_dirty()
    assert "标题" in p._ai_label.text() and "正文部分" in p._ai_label.text()
    assert not p._dirty


def test_instant_render_strategy(qtbot):
    p = ChatPane("t1"); qtbot.addWidget(p)
    p.render_strategy = "instant"
    p.ai_delta("即时")
    assert "即时" in p._ai_label.text()
    p.ai_end("即时")
    assert p._ai_label is None


def test_ai_end_fallback_when_no_stream(qtbot):
    p = ChatPane("t1"); qtbot.addWidget(p)
    p.ai_end("无流兜底消息")
    # 无 _ai_label 时走 append_fallback（新增块）
    assert p._ai_label is None


# ---- 工单 06：工具行「＋ 详情」+ 思考块
def test_tool_line_collapsed_default_then_expands(qtbot, qapp):
    from src.gui.pane import ToolLineWidget

    w = ToolLineWidget("execute", "{'command': 'git status'}", False, "ok out")
    qtbot.addWidget(w)
    w.show()
    qapp.processEvents()
    assert w.btn_toggle.text() == "＋ 详情"
    assert w._detail.isHidden()
    w.btn_toggle.click()
    qapp.processEvents()
    assert w.btn_toggle.text() == "－ 收起"
    assert not w._detail.isHidden()
    assert "git status" in w._detail.text()


def test_tool_line_error_marked(qtbot):
    from src.gui.pane import ToolLineWidget

    w = ToolLineWidget("execute", "{'command': 'x'}", True, "boom")
    qtbot.addWidget(w)
    assert "✗" in w._summary.text()


def test_thinking_box_accumulates_and_toggles(qtbot):
    from src.gui.pane import ThinkingBox

    box = ThinkingBox()
    qtbot.addWidget(box)
    box.add_delta("思考")
    box.add_delta("中…")
    assert "思考中…" in box._body.text()
    assert not box._body.isHidden()  # 默认展开
    box.toggle()
    assert box._body.isHidden()


def test_pane_thinking_delta_creates_box_once(qtbot):
    p = ChatPane("t1"); qtbot.addWidget(p)
    p.thinking_delta("a")
    p.thinking_delta("b")
    assert p._thinking_box is not None
    assert "ab" in p._thinking_box._body.text()
    # 工具事件收掉当前块，下一次思考起新块
    p.append_tool("execute", "{}", False, "ok")
    assert p._thinking_box is None
    p.thinking_delta("c")
    assert p._thinking_box is not None and p._thinking_box._body.text() == "c"


def test_new_session_placeholder_shown_then_hidden(qtbot):
    """空新会话显示占位引导；首条 user/AI 内容出现即隐藏（2026-10-28 报障：
    点「+ 新会话」只见黑屏空面板，无引导）。"""
    from src.gui.pane import ChatPane

    pane = ChatPane("t-empty")
    qtbot.addWidget(pane)
    assert not pane._placeholder.isHidden()  # isVisible 需 show()；用 isHidden 判显隐
    assert "新会话" in pane._placeholder.text()
    pane.append_user("hi")
    assert pane._placeholder.isHidden()


def test_rebuilt_empty_history_placeholder_stays(qtbot):
    """回放/undo 重建 0 条记录的会话：占位保持可见（不出现死黑屏）。"""
    from src.gui.pane import ChatPane

    pane = ChatPane("t-empty2")
    qtbot.addWidget(pane)
    pane.rebuild_from_records([])
    assert not pane._placeholder.isHidden()
