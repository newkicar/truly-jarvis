"""gui15 G5 — 待发队列条：隐藏/重建/压平显示/撤出信号（offscreen）。"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_empty_hides(qtbot):
    from src.gui.queue_strip import QueueStrip

    strip = QueueStrip()
    qtbot.addWidget(strip)
    assert not strip.isVisible()
    assert strip.items() == []


def test_set_items_rebuilds_chips(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton
    from src.gui.queue_strip import QueueStrip

    strip = QueueStrip()
    qtbot.addWidget(strip)
    strip.set_items(["a", "b", "c"])
    assert strip.isVisible() and strip.items() == ["a", "b", "c"]
    labels = strip.findChildren(QLabel)
    btns = strip.findChildren(QPushButton)
    assert [l.text() for l in labels] == ["#1 a", "#2 b", "#3 c"]
    # 每行 2 按钮（插队 + 撤出），行内序：插队在前
    assert [b.text() for b in btns] == ["插队", "撤出"] * 3
    # 重建：整体替换不留残行
    strip.set_items(["x"])
    assert strip.items() == ["x"] and len(strip.findChildren(QLabel)) == 1
    strip.set_items([])
    assert not strip.isVisible()


def test_flattened_label_but_pull_out_emits_original(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton
    from src.gui.queue_strip import QueueStrip

    strip = QueueStrip()
    qtbot.addWidget(strip)
    multi = "line1\nline2"
    strip.set_items([multi])
    # 显示压平单行，原文在 tooltip
    label = strip.findChildren(QLabel)[0]
    assert label.text() == "#1 line1 line2" and label.toolTip() == multi
    emitted = []
    strip.pull_out_requested.connect(emitted.append)
    btn = [b for b in strip.findChildren(QPushButton) if b.text() == "撤出"][0]
    btn.click()
    assert emitted == [multi]  # 原文发出，非压平文本


def test_unbreakable_line_clamps_minimum_width(qtbot):
    """#3：wordwrap 队列行宽度钳 48（先例 CapLabel 78ee003）——不钳时 6000px 不可断
    片段经布局把窗口撑宽；钳后文字在窗口宽度内折行。"""
    from PySide6.QtWidgets import QLabel

    from src.gui.queue_strip import QueueStrip, _WrapLabel

    raw = QLabel("a" * 500)          # 对照：无钳制 QLabel 最小宽=全文宽（窗口撑宽根因）
    qtbot.addWidget(raw)
    assert raw.minimumSizeHint().width() > 48

    lab = _WrapLabel("a" * 500)
    lab.setWordWrap(True)
    qtbot.addWidget(lab)
    assert lab.minimumSizeHint().width() <= 48
    assert lab.wordWrap() is True
    assert lab.sizeHint().width() > 48  # 按可用宽折行，不截断

    strip = QueueStrip()
    qtbot.addWidget(strip)
    strip.set_items(["a" * 500, "b" * 500])
    rows = strip.findChildren(QLabel)
    assert len(rows) == 2
    for i, r in enumerate(rows, start=1):
        assert isinstance(r, _WrapLabel)
        assert r.minimumSizeHint().width() <= 48
        assert r.wordWrap() is True
        assert r.text() == f"#{i} " + ("a" * 500 if i == 1 else "b" * 500)
