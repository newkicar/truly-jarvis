# #21: collect_interrupt_decisions 的一次性覆盖记账（人工放行模型 deny → 线程预算扣减）。

from types import SimpleNamespace

from src.permissions import PROXY_REVIEW_LAST_KEY, PROXY_REVIEW_OVERRIDES_KEY
from src.streaming import collect_interrupt_decisions


def _interrupt() -> SimpleNamespace:
    return SimpleNamespace(
        value={"action_requests": [{"name": "delete", "args": {"path": "x.md"}}]}
    )


def _state(last=None) -> dict:
    state: dict = {"thread_id": "t1"}
    if last is not None:
        state[PROXY_REVIEW_LAST_KEY] = last
    return state


def test_approve_over_deny_records_override() -> None:
    """#21：最近裁决 deny → 人工 approve 记一次该线程覆盖（t1: 1）。"""
    state = _state(
        {
            "tool": "delete",
            "thread_id": "t1",
            "outcome": "deny",
            "rationale": "不可逆",
        }
    )
    out = collect_interrupt_decisions(
        [_interrupt()], lambda inv: {"decision": "approve"}, permission_state=state
    )
    assert out == {"decisions": [{"type": "approve"}]}
    assert state[PROXY_REVIEW_OVERRIDES_KEY] == {"t1": 1}


def test_approve_over_allow_records_nothing() -> None:
    """#21：最近裁决非 deny（allow）→ 不记覆盖。"""
    state = _state({"tool": "delete", "thread_id": "t1", "outcome": "allow"})
    out = collect_interrupt_decisions(
        [_interrupt()], lambda inv: {"decision": "approve"}, permission_state=state
    )
    assert out == {"decisions": [{"type": "approve"}]}
    assert state.get(PROXY_REVIEW_OVERRIDES_KEY, {}) == {}


def test_approve_without_record_records_nothing() -> None:
    """#21：无最近裁决记录 → 不记覆盖。"""
    state = _state()
    out = collect_interrupt_decisions(
        [_interrupt()], lambda inv: {"decision": "approve"}, permission_state=state
    )
    assert out == {"decisions": [{"type": "approve"}]}
    assert state.get(PROXY_REVIEW_OVERRIDES_KEY, {}) == {}
