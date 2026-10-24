"""tui-ux14 #04: JumpInRegistry + MessageQueueJumpInMiddleware 纯逻辑单测（无 UI、无 tmp_path）。"""

import asyncio
import threading
from threading import Barrier

from langchain_core.messages import HumanMessage

from src.jump_in_queue import (
    JumpInRegistry,
    MessageQueueJumpInMiddleware,
    get_current_thread_id,
    set_current_thread_id,
)


class _ChangeCounter:
    """on_change 回调计数器（收集 fire 次数）。"""

    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1


def test_push_returns_thread_count_and_threads_are_isolated():
    reg = JumpInRegistry()
    assert reg.push("A", "a1") == 1
    assert reg.push("A", "a2") == 2
    assert reg.push("B", "b1") == 1
    assert reg.count("A") == 2
    assert reg.count("B") == 1
    assert reg.items("A") == ["a1", "a2"]
    assert reg.items("B") == ["b1"]
    assert reg.items("C") == []
    assert reg.has("A") is True
    assert reg.has("C") is False


def test_pop_first_fifo_and_deletes_key_when_empty():
    reg = JumpInRegistry()
    reg.push("A", "m1")
    reg.push("A", "m2")
    assert reg.pop_first("A") == "m1"
    assert reg.pop_first("A") == "m2"
    assert reg.pop_first("A") is None
    assert reg.has("A") is False
    assert reg.snapshot() == []


def test_pop_item_bounds_and_middle_delete_preserves_order():
    reg = JumpInRegistry()
    for m in ("a", "b", "c"):
        reg.push("A", m)
    assert reg.pop_item("A", 5) is None
    assert reg.pop_item("A", -1) is None
    assert reg.pop_item("B", 0) is None
    assert reg.pop_item("A", 1) == "b"
    assert reg.items("A") == ["a", "c"]
    assert reg.pop_item("A", 0) == "a"
    assert reg.pop_item("A", 0) == "c"
    assert reg.count("A") == 0


def test_drain_fifo_and_second_is_empty():
    reg = JumpInRegistry()
    reg.push("A", "m1")
    reg.push("A", "m2")
    assert reg.drain("A") == ["m1", "m2"]
    assert reg.drain("A") == []
    assert reg.drain("no-such") == []


def test_clear_returns_count_and_idempotent():
    reg = JumpInRegistry()
    for m in ("x", "y", "z"):
        reg.push("A", m)
    assert reg.clear("A") == 3
    assert reg.clear("A") == 0
    assert reg.has("A") is False


def test_readers_do_not_fire_change():
    reg = JumpInRegistry()
    n = _ChangeCounter()
    reg.on_change(n)
    reg.push("A", "m")
    assert n.n == 1
    reg.items("A")
    reg.has("A")
    reg.count("A")
    reg.snapshot()
    assert n.n == 1


def test_change_fire_rules_and_on_change_clear():
    reg = JumpInRegistry()
    n = _ChangeCounter()
    reg.on_change(n)
    # 越界/空操作不 fire
    assert reg.pop_item("A", 0) is None
    assert reg.drain("A") == []
    assert reg.clear("A") == 0
    assert n.n == 0
    # push fire
    reg.push("A", "m")
    assert n.n == 1
    # 非空 drain fire
    assert reg.drain("A") == ["m"]
    assert n.n == 2
    # 再 push fire
    reg.push("A", "m2")
    assert n.n == 3
    # 清空回调后不再计数
    reg.on_change(None)
    reg.push("A", "m3")
    reg.clear("A")
    assert n.n == 3


def test_callback_exception_swallowed():
    reg = JumpInRegistry()

    def bad():
        raise RuntimeError("boom")

    seen = _ChangeCounter()
    reg.on_change(bad)
    reg.on_change(seen)
    assert reg.push("A", "m") == 1
    assert seen.n == 1


def test_concurrent_push_counts_and_per_thread_fifo():
    reg = JumpInRegistry()
    barrier = Barrier(8)
    errors = []

    def worker(i):
        try:
            barrier.wait()
            for j in range(50):
                reg.push(f"t{i}", f"{i}-{j}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    total = 0
    for i in range(8):
        drained = reg.drain(f"t{i}")
        assert drained == [f"{i}-{j}" for j in range(50)], f"t{i} 非 FIFO"
        total += len(drained)
    assert total == 400


def test_thread_local_default_set_clear():
    assert get_current_thread_id() is None
    set_current_thread_id("abc")
    try:
        assert get_current_thread_id() == "abc"
    finally:
        set_current_thread_id(None)
    assert get_current_thread_id() is None


def test_thread_local_isolated_across_threads():
    set_current_thread_id("main-line")
    try:
        result = {}

        def child():
            result["value"] = get_current_thread_id()

        t = threading.Thread(target=child)
        t.start()
        t.join()
        assert result["value"] is None
    finally:
        set_current_thread_id(None)


def test_middleware_name_and_null_args_safe():
    mw = MessageQueueJumpInMiddleware(JumpInRegistry())
    assert mw.name == "jump-in-queue"
    assert mw.before_model(None, None) is None


def test_middleware_no_context_keeps_other_thread_cache():
    reg = JumpInRegistry()
    reg.push("other", "m")
    mw = MessageQueueJumpInMiddleware(reg)  # permission_state=None -> {}
    assert mw.before_model(None, None) is None
    assert reg.items("other") == ["m"]


def test_middleware_drains_state_fifo():
    reg = JumpInRegistry()
    reg.push("A", "m1")
    reg.push("A", "m2")
    mw = MessageQueueJumpInMiddleware(reg, {"thread_id": "A"})
    out = mw.before_model(None, None)
    assert out is not None
    msgs = out["messages"]
    assert len(msgs) == 2
    assert all(isinstance(m, HumanMessage) for m in msgs)
    assert [m.content for m in msgs] == ["m1", "m2"]
    # 空缓存二次调用 -> None（零开销）
    assert mw.before_model(None, None) is None
    assert reg.count("A") == 0


def test_middleware_thread_local_beats_state():
    reg = JumpInRegistry()
    reg.push("local-tid", "L")
    reg.push("state-tid", "S")
    mw = MessageQueueJumpInMiddleware(reg, {"thread_id": "state-tid"})
    set_current_thread_id("local-tid")
    try:
        out = mw.before_model(None, None)
        assert [m.content for m in out["messages"]] == ["L"]
        assert reg.items("state-tid") == ["S"]
    finally:
        set_current_thread_id(None)


def test_middleware_abefore_model_same_semantics():
    reg = JumpInRegistry()
    reg.push("A", "m")
    mw = MessageQueueJumpInMiddleware(reg, {"thread_id": "A"})
    out = asyncio.run(mw.abefore_model(None, None))
    assert [m.content for m in out["messages"]] == ["m"]
    assert asyncio.run(mw.abefore_model(None, None)) is None
