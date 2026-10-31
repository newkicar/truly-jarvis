"""WP1 #6 工单：横向溢出修复的回归测试。

验证 md_render.soft_break / soft_break_html 的断行契约，以及
pane/cards 各长文本消费点在 offscreen 下不再产生横向 overflow。
（严禁 tmp_path / tempfile.mkdtemp；offscreen 平台变量在模块顶部设置）
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel, QFrame  # noqa: E402

from src.gui import md_render  # noqa: E402
from src.gui.pane import _detail_html, ToolLineWidget, ChatPane  # noqa: E402
from src.gui import theme  # noqa: E402


def test_soft_break_chunks_long_tokens():
    out = md_render.soft_break("a" * 150, 60)
    segs = out.split("\n")
    assert all(len(s) <= 60 for s in segs)
    assert "".join(segs) == "a" * 150


def test_soft_break_preserves_existing_newlines():
    out = md_render.soft_break("短\n" + "b" * 70, 30)
    assert out == "短\n" + "b" * 30 + "\n" + "b" * 30 + "\n" + "b" * 10


def test_soft_break_html_keeps_tags():
    html = "<b>" + "x" * 300 + "</b>"
    out = md_render.soft_break_html(html, 80)
    assert "<b>" in out and "</b>" in out
    # 标签内不能被断行：拆分标签后奇数段仍原样
    import re
    parts = re.split(r"(<[^>]*>)", out)
    # 偶数段是文本，应 <= 80 + <br> 碎片
    text_segs = [p for i, p in enumerate(parts) if i % 2 == 0 and p]
    assert all(len(s) <= 80 for s in text_segs), [s for s in text_segs if len(s) > 80]


def test_md_to_qt_html_wraps_long_lines(qapp):
    theme.apply_theme(qapp, "dark")
    md = "\n\n".join(["c" * 300] * 3)
    html = md_render.md_to_qt_html(md)
    # 长 token 被断行，不应出现超长连续文本段
    import re
    parts = re.split(r"(<[^>]*>)", html)
    text_segs = [p for i, p in enumerate(parts) if i % 2 == 0 and p]
    assert all(len(s) <= 200 for s in text_segs), [s[:60] for s in text_segs if len(s) > 200]


def test_detail_html_wraps_args_and_output(qapp):
    theme.apply_theme(qapp, "dark")
    html = _detail_html("A" * 300, "B" * 300, False, 0)
    import re
    parts = re.split(r"(<[^>]*>)", html)
    text_segs = [p for i, p in enumerate(parts) if i % 2 == 0 and p]
    assert all(len(s) <= 200 for s in text_segs), [s[:60] for s in text_segs if len(s) > 200]


def test_tool_line_widget_summary_no_overflow(qtbot):
    w = ToolLineWidget("execute", "A" * 300, False, "B" * 300)
    qtbot.addWidget(w)
    w.show()
    # summary QLabel wordWrap on，minimum width not blown by long tokens
    assert w._summary.wordWrap() is True
    assert w._summary.minimumWidth() == 0


def test_chat_pane_user_subagent_wrap(qtbot):
    p = ChatPane("t1")
    qtbot.addWidget(p)
    p.append_user("U" * 300)
    p.append_subagent("worker", "S" * 300)
    labels = [w for w in p.findChildren(QLabel) if w.objectName() in ("bub-user", "line-sub")]
    assert labels
    for l in labels:
        assert l.wordWrap() is True
        assert l.minimumWidth() == 0


def test_cards_import_soft_break_alias():
    from src.gui import cards
    assert hasattr(cards, "_soft_break")
    assert cards._soft_break is md_render.soft_break
