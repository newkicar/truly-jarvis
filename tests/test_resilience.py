"""执行韧性层测试：错误分类、退避重试、步数软着陆、doom-loop 防御。"""
import pytest

from src import resilience, streaming


# ---------------------------------------------------------------- classify_error

def _exc(name: str, msg: str = "boom") -> Exception:
    return type(name, (Exception,), {})(msg)


@pytest.mark.parametrize(
    ("name", "msg", "expected"),
    [
        ("RateLimitError", "429 too many requests", "retryable"),
        ("APIConnectionError", "connection reset by peer", "retryable"),
        ("APITimeoutError", "request timed out", "retryable"),
        ("BadRequestError", "400 bad request", "retryable"),  # opencode 端点偶发 400
        ("InternalServerError", "500 server error", "retryable"),
        ("AuthenticationError", "invalid api key", "auth"),
        ("PermissionDeniedError", "403 forbidden", "auth"),
        ("BadRequestError", "context_length_exceeded: too many tokens", "context_overflow"),
        ("ValueError", "maximum context length 128k", "context_overflow"),
        ("RuntimeError", "insufficient_quota: billing", "fatal"),
        ("ValueError", "something else broke", "fatal"),
    ],
)
def test_classify_error_decision_table(name, msg, expected):
    assert resilience.classify_error(_exc(name, msg)) == expected


def test_classify_error_aborted():
    assert resilience.classify_error(KeyboardInterrupt()) == "aborted"
    assert resilience.classify_error(_exc("CancelledError", "task cancelled")) == "aborted"


# ---------------------------------------------------------------- 退避与重试

def test_backoff_delay_jitter_range_and_cap():
    for attempt in range(10):
        d = resilience.backoff_delay(attempt)
        base = min(resilience.RETRY_INITIAL_DELAY * resilience.RETRY_BACKOFF_FACTOR**attempt, 30.0)
        assert base * (1 - resilience.RETRY_JITTER) <= d <= base * (1 + resilience.RETRY_JITTER)


def test_backoff_delay_retry_after_wins_and_capped():
    assert resilience.backoff_delay(0, retry_after=8.0) >= 8.0
    assert resilience.backoff_delay(0, retry_after=999.0) <= resilience.RETRY_MAX_DELAY


def test_extract_retry_after_reads_headers():
    err = _exc("RateLimitError", "429")
    err.response = type("R", (), {"headers": {"retry-after": "7"}})()
    assert resilience.extract_retry_after(err) == 7.0
    assert resilience.extract_retry_after(ValueError("x")) is None


def test_with_retry_recovers_then_succeeds():
    sleeps: list[float] = []
    statuses: list[tuple[int, int, float]] = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _exc("APIConnectionError", "connection reset")
        return "ok"

    result = resilience.with_retry(
        flaky,
        attempts=5,
        sleep=sleeps.append,
        on_status=lambda a, t, w: statuses.append((a, t, w)),
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert statuses == [(1, 4, sleeps[0]), (2, 4, sleeps[1])]


def test_with_retry_fatal_raises_immediately():
    calls = {"n": 0}

    def fatal():
        calls["n"] += 1
        raise _exc("AuthenticationError", "401 unauthorized")

    with pytest.raises(Exception):
        resilience.with_retry(fatal, attempts=5, sleep=lambda s: None)
    assert calls["n"] == 1


def test_with_retry_exhausts_attempts():
    calls = {"n": 0}

    def always_retryable():
        calls["n"] += 1
        raise _exc("InternalServerError", "503 unavailable")

    with pytest.raises(Exception):
        resilience.with_retry(always_retryable, attempts=3, sleep=lambda s: None)
    assert calls["n"] == 3


# ---------------------------------------------------------------- 步数软着陆

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage


def _model_request(a_steps: int, system: str = "BASE-PROMPT") -> ModelRequest:
    msgs: list = []
    for i in range(a_steps):
        msgs.append(AIMessage(content=f"step {i}"))
        msgs.append(HumanMessage(content="continue"))
    return ModelRequest(
        model=None,
        messages=msgs,
        system_message=SystemMessage(content=system),
        tools=[],
        state={"messages": []},
    )


def test_step_budget_no_reminder_when_far_from_budget():
    mw = resilience.StepBudgetMiddleware(max_steps=200)
    captured = {}

    def handler(req):
        captured["req"] = req
        return "resp"

    req = _model_request(a_steps=5)
    mw.wrap_model_call(req, handler)
    assert captured["req"].system_message.text == "BASE-PROMPT"


def test_step_budget_soft_lands_near_budget():
    max_steps = 20
    mw = resilience.StepBudgetMiddleware(max_steps=max_steps)
    captured = {}

    def handler(req):
        captured["req"] = req
        return "resp"

    # 已发生 max_steps - 2 步 → 剩余 ≤ SOFT_LAND_STEPS → 注入提醒
    req = _model_request(a_steps=max_steps - 2)
    mw.wrap_model_call(req, handler)
    text = captured["req"].system_message.text
    assert "BASE-PROMPT" in text  # 原 system 不丢
    assert "收敛当前进度" in text


def test_step_budget_hard_stop_when_exhausted():
    mw = resilience.StepBudgetMiddleware(max_steps=10)
    captured = {}

    def handler(req):
        captured["req"] = req
        return "resp"

    req = _model_request(a_steps=15)
    mw.wrap_model_call(req, handler)
    assert "禁止任何工具调用" in captured["req"].system_message.text


# ---------------------------------------------------------------- doom-loop

def _tool_request(name: str, args: dict):
    return type("Req", (), {"tool_call": {"id": "c1", "name": name, "args": args}})()


def test_doom_loop_augments_third_identical_failure():
    mw = resilience.DoomLoopMiddleware(threshold=3)

    def failing_handler(req):
        return ToolMessage(content="command failed", name="execute", tool_call_id="c1", status="error")

    req = _tool_request("execute", {"command": "pytest -q"})
    out1 = mw.wrap_tool_call(req, failing_handler)
    assert out1.content == "command failed"
    out2 = mw.wrap_tool_call(req, failing_handler)
    assert out2.content == "command failed"
    out3 = mw.wrap_tool_call(req, failing_handler)
    assert "连续 3 次" in out3.content
    assert "禁止原样重试" in out3.content


def test_doom_loop_success_resets_streak():
    mw = resilience.DoomLoopMiddleware(threshold=3)

    def handler_err(req):
        return ToolMessage(content="fail", name="execute", tool_call_id="c1", status="error")

    def handler_ok(req):
        return ToolMessage(content="ok", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "pytest -q"})
    mw.wrap_tool_call(req, handler_err)
    mw.wrap_tool_call(req, handler_err)
    mw.wrap_tool_call(req, handler_ok)  # 成功清零（轮询合法）
    out = mw.wrap_tool_call(req, handler_err)
    assert "禁止原样重试" not in out.content


def test_doom_loop_different_args_are_different_signatures():
    mw = resilience.DoomLoopMiddleware(threshold=3)

    def failing_handler(req):
        return ToolMessage(content="fail", name="execute", tool_call_id="c1", status="error")

    mw.wrap_tool_call(_tool_request("execute", {"command": "a"}), failing_handler)
    mw.wrap_tool_call(_tool_request("execute", {"command": "b"}), failing_handler)
    out = mw.wrap_tool_call(_tool_request("execute", {"command": "a"}), failing_handler)
    assert "禁止原样重试" not in out.content


# ---------------------------------------------------------------- run_agent_turn 重试集成

class _Stream:
    def __init__(self):
        self.interrupted = False
        self.interrupts = None
        self.output = None

    def interleave(self, *kinds):
        if False:
            yield


class FlakyAgent:
    """先抛一次 retryable，再正常返回流。"""

    checkpointer = None

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def stream_events(self, payload, *, version, config):
        self.calls += 1
        if self.calls == 1:
            raise self.exc
        assert config["recursion_limit"] >= 10
        return _Stream()


_CB = {
    "on_subagent": lambda *a: None,
    "on_tool_call": lambda *a: None,
    "on_message_delta": lambda d: None,
}


def test_run_agent_turn_retries_on_transient_error(monkeypatch):
    monkeypatch.setattr(resilience, "backoff_delay", lambda attempt, retry_after=None: 0.01)
    statuses = []
    cb = {**_CB, "on_status": statuses.append}
    agent = FlakyAgent(_exc("APIConnectionError", "connection reset"))
    ok = streaming.run_agent_turn(
        agent, "t", "hi", handle_interrupts=lambda _: None, callbacks=cb
    )
    assert ok is True
    assert agent.calls == 2
    assert any("重试" in s for s in statuses)


def test_run_agent_turn_does_not_retry_auth_error(monkeypatch):
    called = {"sleep": 0}

    def no_sleep(_):
        called["sleep"] += 1

    monkeypatch.setattr(resilience, "backoff_delay", no_sleep)
    agent = FlakyAgent(_exc("AuthenticationError", "401 invalid api key"))
    with pytest.raises(Exception):
        streaming.run_agent_turn(
            agent, "t", "hi", handle_interrupts=lambda _: None, callbacks=dict(_CB)
        )
    assert agent.calls == 1
    assert called["sleep"] == 0


def test_run_agent_turn_recursion_error_lands_softly():
    from langgraph.errors import GraphRecursionError

    class ExplodingAgent:
        checkpointer = None

        def __init__(self):
            self.calls = 0

        def stream_events(self, payload, *, version, config):
            self.calls += 1
            raise GraphRecursionError("recursion limit reached")

    agent = ExplodingAgent()
    fallbacks = []
    statuses = []
    cb = {
        **_CB,
        "on_status": statuses.append,
        "on_message_delta": lambda d: None,
    }
    ok = streaming.run_agent_turn(
        agent,
        "t",
        "hi",
        handle_interrupts=lambda _: None,
        callbacks=cb,
        on_fallback_message=fallbacks.append,
        max_steps=77,
    )
    assert ok is False
    assert any("步数超过上限 77" in s for s in statuses + fallbacks)


def test_run_agent_turn_uses_max_steps_config():
    class RecordingAgent(FlakyAgent):
        seen_configs = []

        def stream_events(self, payload, *, version, config):
            self.seen_configs.append(config)
            return super().stream_events(payload, version=version, config=config)

    agent = RecordingAgent(_exc("NeverRaised", "x"))
    with pytest.raises(Exception):
        streaming.run_agent_turn(
            agent, "t", "hi", handle_interrupts=lambda _: None, callbacks=dict(_CB), max_steps=123
        )
    assert agent.seen_configs[0]["recursion_limit"] == 123
