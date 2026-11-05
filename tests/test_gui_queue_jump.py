"""gui15 G5#2 — 队列条「插队」按钮：撤出 FIFO + 立即注入 JumpInRegistry（offscreen）。

对标 codex queued-chip Steer（issue #32709）：排队消息可逐条提升进当前回合。
运行分支 → registry 缓存（before_model 注入，图片走路径引用 fallback）；
空闲/竞态边界 → 直接重投 start_turn。
"""
import os
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.jump_in_queue import JumpInRegistry
from tests.gui_fakes import new_home, cleanup_home
from tests.test_gui_presenter import _fake_runtime


def test_strip_rows_carry_jump_and_pull_out_buttons(qtbot):
    from PySide6.QtWidgets import QPushButton
    from src.gui.queue_strip import QueueStrip

    strip = QueueStrip()
    qtbot.addWidget(strip)
    strip.set_items(["a", "b"])
    # 每行 2 按钮（插队 + 撤出）
    btns = strip.findChildren(QPushButton)
    assert [b.text() for b in btns] == ["插队", "撤出", "插队", "撤出"]
    jumped, pulled = [], []
    strip.jump_requested.connect(jumped.append)
    strip.pull_out_requested.connect(pulled.append)
    btns[0].click()  # 第 1 行插队
    btns[1].click()  # 第 1 行撤出
    btns[2].click()
    assert jumped == ["a", "b"] and pulled == ["a"]


def test_jump_in_running_turn_pushes_to_registry(qtbot):
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter

    home = new_home()
    try:
        rt = _fake_runtime()
        rt.registry = JumpInRegistry()
        bridge = UiBridge()
        p = GuiPresenter(rt, bridge)
        win = MainWindow(p, bridge)
        win._switch_to("t1")
        # t1 有 running 回合（gate 直接置位，不起 worker）+ 1 条排队项
        assert p.gate.try_start("t1", "m1") == "started"
        assert p.gate.try_start("t1", "m2", images=["C:\\fake\\x.png"]) == "queued"
        assert p.gate.is_running("t1")

        win._on_queue_jump("m2")

        # 撤出 FIFO（防回合末重复重投）+ 注入 registry（图片以路径引用 fallback）
        assert p.gate.queued_count("t1") == 0
        items = rt.registry.items("t1")
        assert len(items) == 1
        assert "m2" in items[0] and "图片 #1 路径: C:\\fake\\x.png" in items[0]
        assert "已插队" in win.status_label.text()
        assert not win.queue_strip.isVisible()  # 队列空了 → 条隐藏
        p.gate.finish_full("t1")
    finally:
        cleanup_home(home)


def test_jump_in_no_image_keeps_plain_text(qtbot):
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter

    home = new_home()
    try:
        rt = _fake_runtime()
        rt.registry = JumpInRegistry()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, UiBridge())
        win._switch_to("t1")
        p.gate.try_start("t1", "m1")
        p.gate.try_start("t1", "plain")
        win._on_queue_jump("plain")
        assert rt.registry.items("t1") == ["plain"]
        p.gate.finish_full("t1")
    finally:
        cleanup_home(home)


def test_jump_in_idle_falls_back_to_replay(qtbot, monkeypatch):
    """边界：点击时回合已结束（正常不可达）→ 撤出队列后直接重投，不双发。"""
    from src import streaming
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter

    home = new_home()
    try:
        rt = _fake_runtime()
        rt.registry = JumpInRegistry()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, UiBridge())
        win._switch_to("t1")
        # 模拟：队列里有项但回合未在跑（直接塞队列，不入门）
        p.gate._queues["t1"] = deque([("m2", [])])
        calls = []
        monkeypatch.setattr(streaming, "run_agent_turn",
                            lambda agent, tid, user_input, **kw: calls.append((tid, user_input)))
        win._on_queue_jump("m2")
        assert p.gate.queued_count("t1") == 0
        assert rt.registry.items("t1") == []  # 未注入 registry（走重投路径）
        assert ("t1", "m2") in calls           # start_turn 立即起回合
    finally:
        cleanup_home(home)


def test_jump_in_consumed_item_is_noop(qtbot):
    """竞态：条目在点击与处理之间已被消费 → 不注入 registry，只刷新条。"""
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter

    home = new_home()
    try:
        rt = _fake_runtime()
        rt.registry = JumpInRegistry()
        p = GuiPresenter(rt, UiBridge())
        win = MainWindow(p, UiBridge())
        win._switch_to("t1")
        p.gate.try_start("t1", "m1")  # running，但队列为空
        win._on_queue_jump("ghost")
        assert rt.registry.items("t1") == []
        p.gate.finish_full("t1")
    finally:
        cleanup_home(home)
