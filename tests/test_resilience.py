"""执行韧性层测试：错误分类、退避重试、步数软着陆、doom-loop 防御、工具异常兜底。"""
from unittest.mock import patch

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


def test_doom_loop_counts_execute_exit_code_failures():
    """deepagents execute 失败时 status 仍是 success，失败只体现在内容尾部
    "[Command failed with exit code N]"——doom loop 必须识别这种失败形态（坦克大战事故）。"""
    mw = resilience.DoomLoopMiddleware(threshold=3)

    def exit_fail_handler(req):
        return ToolMessage(
            content="[stderr] 命令语法不正确。\n\nExit code: 1\n[Command failed with exit code 1]",
            name="execute",
            tool_call_id="c1",
        )  # status 默认 success

    req = _tool_request("execute", {"command": "mkdir /workspace/tmp-javis-demo"})
    mw.wrap_tool_call(req, exit_fail_handler)
    mw.wrap_tool_call(req, exit_fail_handler)
    out = mw.wrap_tool_call(req, exit_fail_handler)
    assert "禁止原样重试" in out.content


def test_doom_loop_command_succeeded_marker_is_success():
    mw = resilience.DoomLoopMiddleware(threshold=2)

    def exit_ok_handler(req):
        return ToolMessage(content="done\n[Command succeeded with exit code 0]", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "echo ok"})
    out = None
    for _ in range(4):
        out = mw.wrap_tool_call(req, exit_ok_handler)
    assert out is not None and "禁止原样重试" not in out.content


def test_doom_loop_exit_code_nonzero_triggers_at_threshold():
    mw = resilience.DoomLoopMiddleware(threshold=2)

    def exit_fail_handler(req):
        return ToolMessage(content="boom\n[Command failed with exit code 2]", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "bad"})
    mw.wrap_tool_call(req, exit_fail_handler)
    out = mw.wrap_tool_call(req, exit_fail_handler)
    assert "禁止原样重试" in out.content


# ---------------------------------------------------------------- doom-loop 硬熔断


def test_doom_loop_hard_break_at_limit():
    """连续失败到 hard_limit：不再执行工具，返回 error ToolMessage（代码边界）。"""
    mw = resilience.DoomLoopMiddleware(threshold=3, hard_limit=5)
    calls = []

    def exit_fail_handler(req):
        calls.append(1)
        return ToolMessage(content="boom\n[Command failed with exit code 1]", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "stuck"})
    outs = [mw.wrap_tool_call(req, exit_fail_handler) for _ in range(4)]
    assert len(calls) == 4, "前 4 次应真实执行"
    assert "禁止原样重试" in outs[2].content, "第 3 次起软引导"
    assert outs[3].status != "error"

    out5 = mw.wrap_tool_call(req, exit_fail_handler)
    assert len(calls) == 4, "第 5 次不应再执行工具（硬熔断）"
    assert out5.status == "error"
    assert "harness 拒绝执行" in out5.content
    assert "换方法类别" in out5.content


def test_doom_loop_hard_break_persists_until_args_change():
    """熔断后同名同参调用持续被拒（不执行）；参数变化后恢复执行。"""
    mw = resilience.DoomLoopMiddleware(threshold=2, hard_limit=3)
    calls = []

    def fail_handler(req):
        calls.append(1)
        return ToolMessage(content="fail\n[Command failed with exit code 1]", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "stuck"})
    for _ in range(3):
        mw.wrap_tool_call(req, fail_handler)
    assert len(calls) == 2  # 第 3 次已被熔断拦截

    out = mw.wrap_tool_call(req, fail_handler)
    assert out.status == "error" and "harness 拒绝执行" in out.content
    assert len(calls) == 2, "熔断后不再执行"

    # 参数变化 = 新签名，恢复执行
    out_new = mw.wrap_tool_call(_tool_request("execute", {"command": "changed"}), fail_handler)
    assert len(calls) == 3
    assert out_new.status != "error" or "harness 拒绝执行" not in str(out_new.content)


def test_doom_loop_success_clears_hard_break():
    """成功清零只对「还能执行」的签名生效；已达熔断线的签名被锁死（设计行为）。"""
    mw = resilience.DoomLoopMiddleware(threshold=2, hard_limit=3)

    def fail_handler(req):
        return ToolMessage(content="fail\n[Command failed with exit code 1]", name="execute", tool_call_id="c1")

    def ok_handler(req):
        return ToolMessage(content="done\n[Command succeeded with exit code 0]", name="execute", tool_call_id="c1")

    req = _tool_request("execute", {"command": "x"})
    mw.wrap_tool_call(req, fail_handler)
    mw.wrap_tool_call(req, fail_handler)  # streak=2 = hard_limit-1 → 签名锁定
    out_locked = mw.wrap_tool_call(req, ok_handler)
    assert out_locked.status == "error" and "harness 拒绝执行" in out_locked.content

    # 换参数 = 新签名，正常执行且成功清零自己的计数
    other = _tool_request("execute", {"command": "y"})
    out_ok = mw.wrap_tool_call(other, ok_handler)
    assert out_ok.content.startswith("done")
    out_ok2 = mw.wrap_tool_call(other, ok_handler)
    assert out_ok2.content.startswith("done"), "新签名不受旧签名熔断影响"

    # 锁定的签名持续被拒
    out_again = mw.wrap_tool_call(req, ok_handler)
    assert "harness 拒绝执行" in out_again.content


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

    def stream_events(self, payload, *, version, config, control=None):
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

        def stream_events(self, payload, *, version, config, control=None):
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

        def stream_events(self, payload, *, version, config, control=None):
            self.seen_configs.append(config)
            return super().stream_events(payload, version=version, config=config)

    agent = RecordingAgent(_exc("NeverRaised", "x"))
    with pytest.raises(Exception):
        streaming.run_agent_turn(
            agent, "t", "hi", handle_interrupts=lambda _: None, callbacks=dict(_CB), max_steps=123
        )
    assert agent.seen_configs[0]["recursion_limit"] == 123


# --------------------------------------------------- ToolErrorBoundaryMiddleware 单元


def test_tool_error_boundary_catches_sync():
    from langchain_core.messages import ToolMessage

    mw = resilience.ToolErrorBoundaryMiddleware()

    class FakeRequest:
        tool_call = {"name": "write_file", "id": "tc-1", "args": {"file_path": "/workspace/D:/tmp/x.py"}}

    def boom(_req):
        raise ValueError("Path:D:\\tmp\\x.py outside root directory: /workspace")

    result = mw.wrap_tool_call(FakeRequest(), boom)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "outside root directory" in result.content
    assert "ToolErrorBoundaryMiddleware" not in result.content  # 不能暴露中间件名
    assert "不要原样重试" in result.content


@pytest.mark.asyncio
async def test_tool_error_boundary_catches_async():
    from langchain_core.messages import ToolMessage

    mw = resilience.ToolErrorBoundaryMiddleware()

    class FakeRequest:
        tool_call = {"name": "edit_file", "id": "tc-2", "args": {"file_path": "/workspace/notes.txt"}}

    async def boom(_req):
        raise OSError("disk full")

    result = await mw.awrap_tool_call(FakeRequest(), boom)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "OSError: disk full" in result.content


def test_tool_error_boundary_passes_through_ok():
    mw = resilience.ToolErrorBoundaryMiddleware()

    class FakeRequest:
        tool_call = {"name": "read_file", "id": "tc-3", "args": {}}

    ok_msg = "file contents"

    def success(_req):
        from langchain_core.messages import ToolMessage

        return ToolMessage(content=ok_msg, tool_call_id="tc-3")

    result = mw.wrap_tool_call(FakeRequest(), success)
    assert result.content == ok_msg


# ---- agent-level integration：HITL 放行后越界写入 → 模型收到错误数据，继续 DONE


def test_tool_boundary_hilt_resume_no_crash():
    """复现真实事故链：模型用 /workspace/D:/tmp 路径写文件 → HITL 放行 →
    backend ValueError → 没有 ToolErrorBoundaryMiddleware 时整轮炸穿；
    有兜底后模型收到错误数据，继续对话到 DONE。"""
    import tempfile
    from pathlib import Path

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.types import Command

    from src.agent import build_agent
    from tests.conftest import make_fake_config

    tmp = Path(tempfile.mkdtemp())
    cfg = make_fake_config(tmp)

    # #10 后 virtual_mode=False，畸形虚拟前缀路径不再触发 backend ValueError；
    # 改用「write 已存在的目录」作为稳定的 backend 异常源。
    blocker = Path(str(cfg.project_root)) / "blocker"
    blocker.mkdir(parents=True, exist_ok=True)

    class ScriptedModel(BaseChatModel):
        """第 1 轮：write_file 一个已存在的目录（backend 必然报错）；第 2 轮：DONE。"""
        step: int = 0

        def bind_tools(self, tools, **kw):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kw):
            self.step += 1
            if self.step == 1:
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="", tool_calls=[{
                        "name": "write_file",
                        "args": {"file_path": str(blocker), "content": "x"},
                        "id": "c1", "type": "tool_call",
                    }]
                ))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="DONE"))])

        @property
        def _llm_type(self):
            return "scripted"

    agent = build_agent(cfg, model=ScriptedModel())
    config = {"configurable": {"thread_id": "tb-hilt-1"}}

    # 第一轮：invoke → HITL 中断
    result = agent.invoke({"messages": [{"role": "user", "content": "go"}]}, config=config)
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    assert interrupts and len(interrupts) > 0, "应触发 HITL 中断"

    # 放行 resume
    result = agent.invoke(
        Command(resume={"decisions": [{"type": "approve"}]}),
        config=config,
    )

    # 断言：不再炸穿，模型收到错误数据并继续到 DONE
    messages = result["messages"]
    tool_msgs = [m for m in messages if type(m).__name__ == "ToolMessage"]
    assert len(tool_msgs) >= 1, "应有 ToolMessage（backend 错误数据）"
    assert tool_msgs[-1].status == "error"
    assert (
        "ValueError" in tool_msgs[-1].content
        or "outside root" in tool_msgs[-1].content
        or "Error writing file" in tool_msgs[-1].content
    )
    # 最后一条是模型的 DONE
    assert messages[-1].content == "DONE"


# ---- finalize 回归：fatal 异常后 finalize_turn 被调用


def test_run_agent_turn_finalize_on_fatal():
    with patch.object(streaming.commands, "finalize_turn") as mock_fin:
        with pytest.raises(Exception):
            streaming.run_agent_turn(
                FlakyAgent(_exc("ValueError", "fatal blow")),
                "thread-fin",
                "hi",
                handle_interrupts=lambda _: None,
                callbacks=_CB,
            )
        # 两次调用：①新轮次开始前清理上一轮 ②fatal 异常兜底
        assert mock_fin.call_count == 2


# ---------------------------------------------------------------- 步数上限强制交接


def test_run_agent_turn_force_handoff_on_recursion_error():
    """到顶不许摆烂：GraphRecursionError 时用 _jarvis_model 生成结构化交接。"""
    from langgraph.errors import GraphRecursionError

    class HandoffModel:
        def invoke(self, messages):
            last = messages[-1].content
            assert "结构化交接" in last
            return type("Resp", (), {"content": "1) 已完成 X\n2) 未完成 Y\n3) 建议 Z"})()

    class RecursionAgent:
        checkpointer = None

        def __init__(self):
            self.calls = 0
            self._jarvis_model = HandoffModel()

        def get_state(self, config):
            return type(
                "State",
                (),
                {"values": {"messages": [{"role": "user", "content": "task"}]}},
            )()

        def stream_events(self, payload, *, version, config, control=None):
            self.calls += 1
            raise GraphRecursionError("limit")

    agent = RecursionAgent()
    fallbacks = []
    statuses = []
    cb = {**_CB, "on_status": statuses.append, "on_message_delta": lambda d: None}
    ok = streaming.run_agent_turn(
        agent,
        "t",
        "hi",
        handle_interrupts=lambda _: None,
        callbacks=cb,
        on_fallback_message=fallbacks.append,
        max_steps=50,
    )
    assert ok is False
    joined = "\n".join(fallbacks)
    assert "已完成 X" in joined and "建议 Z" in joined, "交接文本应输出给用户"
    assert any("步数超过上限 50" in s for s in statuses), "状态行提示上限"


def test_run_agent_turn_handoff_falls_back_without_model():
    """无 _jarvis_model（如旧测试桩）：回落到原提示，不崩。"""
    from langgraph.errors import GraphRecursionError

    class BareAgent:
        checkpointer = None

        def stream_events(self, payload, *, version, config, control=None):
            raise GraphRecursionError("limit")

    fallbacks = []
    statuses = []
    cb = {**_CB, "on_status": statuses.append, "on_message_delta": lambda d: None}
    ok = streaming.run_agent_turn(
        BareAgent(),
        "t",
        "hi",
        handle_interrupts=lambda _: None,
        callbacks=cb,
        on_fallback_message=fallbacks.append,
        max_steps=15,
    )
    assert ok is False
    assert any("步数超过上限 15" in s for s in statuses + fallbacks)

# ---------------------------------------------------------------- 停滞防御（StagnationGuard）

_BASE = "长春 逐小时天气 10月25日 周日 每小时 气温 降水概率"


def _stagnation_ok_handler():
    def handler(req):
        return ToolMessage(
            content="result", name=req.tool_call["name"], tool_call_id="c1"
        )
    return handler


def _stagnation_requests(thread_id=None):
    def make(name, args, req_id="c1"):
        req = type("Req", (), {"tool_call": {"id": req_id, "name": name, "args": args}})()
        if thread_id is not None:
            req.state = {"configurable": {"thread_id": thread_id}}
        return req
    return make


def test_arg_tokens_cjk_ascii_mixed_and_none():
    assert resilience.arg_tokens(None) == frozenset()
    toks = resilience.arg_tokens({"query": "长春 天气 2026"})
    assert "长春" in toks      # CJK 双字
    assert "2026" in toks      # ASCII 数字串
    assert "" not in toks


def test_arg_tokens_single_ascii_char_excluded():
    # key/value 均为单字母（<2 字符）-> 空 token 集
    assert resilience.arg_tokens({"a": "x"}) == frozenset()


def test_token_similarity_edge_cases():
    empty = frozenset()
    assert resilience.token_similarity(empty, empty) == 1.0
    assert resilience.token_similarity(empty, frozenset({"abc"})) == 0.0
    assert resilience.token_similarity(frozenset({"abc"}), empty) == 0.0
    assert resilience.token_similarity(frozenset({"abc"}), frozenset({"xyz"})) == 0.0
    # 单字母 ASCII 参数 -> 空 token 集 -> 双空相似度 1.0（不误判近似）
    assert resilience.token_similarity(
        resilience.arg_tokens({"query": "x"}), resilience.arg_tokens({"query": "y"})
    ) == 1.0


def test_stagnation_guard_ignores_legitimate_polling():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()

    calls = []

    def handler(req):
        calls.append(req.tool_call["args"])
        return ToolMessage(content="ok", name="quick_search", tool_call_id="c1")

    for i in ("123", "456", "789", "101112", "20212223"):
        out = mw.wrap_tool_call(
            make("quick_search", {"job": "ci-status", "id": i}), handler
        )
        assert out.content == "ok"
        assert "[系统提示]" not in out.content
    assert len(calls) == 5


def test_stagnation_guard_soft_guidance_at_third_near_dup():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    seq = [_BASE, _BASE + " 2026", _BASE + " 2026年", _BASE + " 2026年10月"]
    executed = []

    def handler(req):
        executed.append(req.tool_call["args"])
        return ToolMessage(content="result", name="quick_search", tool_call_id="c1")

    results = [
        mw.wrap_tool_call(make("quick_search", {"query": q}), handler) for q in seq
    ]
    assert len(executed) == 4
    for r in results[:3]:
        assert "[系统提示]" not in r.content
    assert results[3].content.endswith(
        resilience.STAGNATION_SOFT_GUIDANCE.format(n=3, tool="quick_search")
    )


def test_stagnation_guard_hard_break_at_sixth_near_dup():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    seq = [
        _BASE,
        _BASE + " 2026",
        _BASE + " 2026年",
        _BASE + " 2026年10月",
        _BASE + "2026年10月25日",
        _BASE + "2026年10月25日 周日",
        _BASE + "2026年10月25日 周日 逐小时",
    ]
    executed = []

    def handler(req):
        executed.append(req.tool_call["args"])
        return ToolMessage(content="result", name="quick_search", tool_call_id="c1")

    results = [
        mw.wrap_tool_call(make("quick_search", {"query": q}), handler) for q in seq
    ]
    assert len(executed) == 6
    assert "[系统提示]" in results[3].content
    blocked = results[6]
    assert blocked.status == "error"
    assert resilience.STAGNATION_BLOCKED_MARKER in blocked.content
    assert "连续 6 次" in blocked.content
    assert blocked.name == "quick_search"
    assert blocked.tool_call_id == "c1"


def test_stagnation_guard_reset_on_distinct_args():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    handler = _stagnation_ok_handler()
    for q in (_BASE, _BASE + " 2026", _BASE + " 2026年"):
        mw.wrap_tool_call(make("quick_search", {"query": q}), handler)
    out4 = mw.wrap_tool_call(
        make("quick_search", {"query": _BASE + " 2026年10月"}), handler
    )
    assert "[系统提示]" in out4.content
    for i in range(3):
        r = mw.wrap_tool_call(
            make("quick_search", {"query": f"东京 地铁 路线 车站{i}"}), handler
        )
        assert "[系统提示]" not in r.content


def test_stagnation_guard_tools_independent():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    handler = _stagnation_ok_handler()
    seqA = ["长春 逐小时天气 每小时 气温 降水概率"]
    seqA.append(seqA[0] + " 每小时")
    seqA.append(seqA[1] + " 温度")
    seqA.append(seqA[2] + " 周日 预报")
    seqB = ["特斯拉 股价 周线 收盘价 走势"]
    seqB.append(seqB[0] + " 收盘")
    seqB.append(seqB[1] + " 收盘 涨跌")
    seqB.append(seqB[2] + " 涨跌 幅度")
    resA, resB = [], []
    for i in range(4):
        resA.append(mw.wrap_tool_call(make("quick_search", {"query": seqA[i]}), handler))
        resB.append(mw.wrap_tool_call(make("deep_search", {"query": seqB[i]}), handler))
    for r in resA[:3] + resB[:3]:
        assert "[系统提示]" not in r.content
    assert "[系统提示]" in resA[3].content
    assert "[系统提示]" in resB[3].content


def test_stagnation_guard_thread_isolation():
    mw = resilience.StagnationGuardMiddleware()
    make_a = _stagnation_requests(thread_id="a")
    make_b = _stagnation_requests(thread_id="b")
    handler = _stagnation_ok_handler()
    seq = [_BASE, _BASE + " 2026", _BASE + " 2026年", _BASE + " 2026年10月"]
    res_a, res_b = [], []
    for i in range(4):
        res_a.append(mw.wrap_tool_call(make_a("quick_search", {"query": seq[i]}), handler))
        res_b.append(mw.wrap_tool_call(make_b("quick_search", {"query": seq[i]}), handler))
    for r in res_a[:3] + res_b[:3]:
        assert "[系统提示]" not in r.content
    assert "[系统提示]" in res_a[3].content
    assert "[系统提示]" in res_b[3].content
    assert res_a[3].status != "error" and res_b[3].status != "error"


def test_stagnation_guard_async_path():
    import asyncio

    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    seq = [
        _BASE,
        _BASE + " 2026",
        _BASE + " 2026年",
        _BASE + " 2026年10月",
        _BASE + "2026年10月25日",
        _BASE + "2026年10月25日 周日",
        _BASE + "2026年10月25日 周日 逐小时",
    ]
    executed = []

    async def handler(req):
        executed.append(req.tool_call["args"])
        return ToolMessage(content="result", name="quick_search", tool_call_id="c1")

    async def run():
        return [
            await mw.awrap_tool_call(make("quick_search", {"query": q}), handler)
            for q in seq
        ]

    results = asyncio.run(run())
    assert len(executed) == 6
    assert "[系统提示]" in results[3].content
    assert results[6].status == "error"
    assert resilience.STAGNATION_BLOCKED_MARKER in results[6].content


def test_stagnation_guard_changchun_report_regression():
    mw = resilience.StagnationGuardMiddleware()
    make = _stagnation_requests()
    executed = 0

    def counting_handler(req):
        nonlocal executed
        executed += 1
        return ToolMessage(content="result", name="quick_search", tool_call_id="c1")

    q = _BASE
    seq = [
        q,
        q + " 2026",
        q + " 2026年",
        q + " 2026年10月",
        q + " 2026年10月25日",
        q + " 2026年10月25日 周日",
        q + " 2026年10月25日 周日 逐小时",
        q + " 2026年10月25日 周日 逐小时 天气",
        q + " 2026年10月25日 周日 逐小时 天气 预报",
    ]
    results = [
        mw.wrap_tool_call(make("quick_search", {"query": qq}), counting_handler)
        for qq in seq
    ]
    assert executed == 6
    assert "[系统提示]" in results[3].content
    for r in results[6:]:
        assert r.status == "error"
        assert resilience.STAGNATION_BLOCKED_MARKER in r.content
