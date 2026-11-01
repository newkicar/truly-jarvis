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
    assert len(btns) == 3
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
    btn = strip.findChildren(QPushButton)[0]
    btn.click()
    assert emitted == [multi]  # 原文发出，非压平文本
