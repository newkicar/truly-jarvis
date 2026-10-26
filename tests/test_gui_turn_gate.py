"""工单 01 — 每 thread 回合门 + FIFO 队列（纯逻辑）。"""
from src.gui.turn_gate import TurnGate


def test_start_when_idle_admits():
    g = TurnGate()
    assert g.try_start("a", "hi") == "started"
    assert g.is_running("a")


def test_submit_while_running_queues_and_replays_fifo():
    g = TurnGate()
    assert g.try_start("a", "m1") == "started"
    assert g.try_start("a", "m2") == "queued"
    assert g.try_start("a", "m3") == "queued"
    assert g.queued_count("a") == 2
    # 回合结束 → 出队 m2
    assert g.finish("a") == "m2"
    # 立即重投 m2 成 running
    assert g.try_start("a", "m2") == "started"
    assert g.finish("a") == "m3"
    assert g.finish("a") is None


def test_threads_are_independent():
    g = TurnGate()
    assert g.try_start("a", "x") == "started"
    assert g.try_start("b", "y") == "started"  # 跨 thread 并行
    assert g.running_threads() == ["a", "b"]
    g.request_cancel("a")
    assert g.is_cancelled("a")
    assert not g.is_cancelled("b")


def test_cancel_flag_resets_on_new_turn():
    g = TurnGate()
    g.try_start("a", "m")
    g.request_cancel("a")
    assert g.is_cancelled("a")
    g.finish("a")
    # 新回合清位
    assert g.try_start("a", "next") == "started"
    assert not g.is_cancelled("a")
