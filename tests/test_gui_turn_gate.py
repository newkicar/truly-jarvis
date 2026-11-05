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


def test_queued_texts_returns_fifo_copy():
    g = TurnGate()
    g.try_start("a", "m1")
    assert g.queued_texts("a") == []
    g.try_start("a", "m2")
    g.try_start("a", "m3")
    got = g.queued_texts("a")
    assert got == ["m2", "m3"]
    got.append("zzz")  # 副本，不动队列本体
    assert g.queued_texts("a") == ["m2", "m3"]
    assert g.queued_texts("b") == []


def test_pull_out_semantics():
    g = TurnGate()
    g.try_start("a", "m1")
    g.try_start("a", "x")
    g.try_start("a", "y")
    # 未排队 / 未命中
    assert g.pull_out("b", "x") is False
    assert g.pull_out("a", "nope") is False
    # 命中移除原文精确匹配
    assert g.pull_out("a", "x") is True
    assert g.queued_texts("a") == ["y"]
    # 空队列
    assert g.pull_out("a", "y") is True
    assert g.queued_texts("a") == []
    assert g.pull_out("a", "y") is False


def test_queued_items_carry_images_and_fifo_replay():
    """#2：队列载荷=(原文,图片列表) FIFO 出队；started 分支忽略 images。"""
    g = TurnGate()
    assert g.try_start("a", "m1") == "started"
    assert g.try_start("a", "m2", images=["i1.png"]) == "queued"
    assert g.try_start("a", "m3") == "queued"
    assert g.finish_full("a") == ("m2", ["i1.png"])
    assert g.finish_full("a") == ("m3", [])          # 无图=空列表
    assert g.finish_full("a") is None


def test_queued_images_are_copied_not_shared():
    """#2：images 入队按拷贝语义——调用方后续改动不污染队列项。"""
    g = TurnGate()
    assert g.try_start("a", "m1") == "started"
    imgs = ["i.png"]
    assert g.try_start("a", "m2", images=imgs) == "queued"
    imgs.append("j.png")
    assert g.finish_full("a") == ("m2", ["i.png"])


def test_pull_out_full_returns_payload_or_none():
    """#2：pull_out_full 返回(原文,图片)并移除；线程不符/未命中/已移除=None。"""
    g = TurnGate()
    g.try_start("a", "m1")
    assert g.try_start("a", "m2", images=["p.png"]) == "queued"
    assert g.pull_out_full("b", "m2") is None
    assert g.pull_out_full("a", "nope") is None
    assert g.pull_out_full("a", "m2") == ("m2", ["p.png"])
    assert g.pull_out_full("a", "m2") is None

def test_clear_queue_and_clear_all_queues():
    """项目移除/释放路径：clear_queue 弹空返回条数（空=0、幂等）；clear_all_queues 弹空全部 thread。"""
    g = TurnGate()
    g.try_start("a", "m1")
    g.try_start("a", "q1")
    g.try_start("a", "q2")
    g.try_start("b", "n1")
    g.try_start("b", "p1")
    assert g.clear_queue("a") == 2
    assert g.clear_queue("a") == 0            # 幂等
    assert g.queued_texts("a") == []
    assert g.queued_texts("b") == ["p1"]     # 他 thread 不受影响（n1 是已开始的回合消息，不在队列）
    assert g.clear_all_queues() == 1          # 只剩 b
    assert g.queued_texts("b") == []
    assert g.clear_all_queues() == 0
