# proxy.review 裁决层（#19）单测：纯内存假模型，自建目录纪律（不依赖 tmp_path）。

import json
import os
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.proxy_reviewer as pr
from src import jump_in_queue as jq
from src.config import resolve_proxy_review
from src.permissions import (
    GATED_TOOLS,
    PROXY_REVIEW_BREAKERS_KEY,
    PROXY_REVIEW_KEY,
    PROXY_REVIEW_LAST_KEY,
    PROXY_REVIEW_OVERRIDES_KEY,
    build_permission_interrupts,
    proxy_on,
    yolo_on,
)

ALLOW_JSON = '{"risk": "low", "authorization": "low", "rationale": "低危"}'
CRITICAL_JSON = '{"risk": "critical", "authorization": "critical", "rationale": "不可逆"}'
ASK_JSON = '{"risk": "high", "authorization": "low", "rationale": "定不了"}'

# 每个 gated 工具各取一组「穿过地板 → 维持 ask」的参数（execute 未命中只读表）
_GATE_ARGS = {
    "execute": {"command": "curl http://example.com"},
    "write_file": {"file_path": "../outside.md", "content": "x"},
    "edit_file": {"file_path": "../outside.md", "old_str": "a", "new_str": "b"},
    "delete": {"path": "keep-me.md"},
}


def test_gate_args_cover_all_gated_tools():
    assert set(_GATE_ARGS) == set(GATED_TOOLS)


@pytest.fixture(autouse=True)
def env():
    jq.set_current_thread_id(None)
    pr.clear_review_cache()
    d = os.path.join(".scratch", "proxy-reviewer-test-tmp", uuid.uuid4().hex)
    os.makedirs(d)
    namespace = SimpleNamespace(tmp=Path(d), audit=Path(d) / "audit.jsonl")
    yield namespace
    shutil.rmtree(d, ignore_errors=True)
    parent = os.path.dirname(d)
    try:
        os.rmdir(parent)
    except OSError:
        pass
    jq.set_current_thread_id(None)
    pr.clear_review_cache()


class FakeModel:
    def __init__(self, content="", error=None):
        self.content = content
        self.error = error
        self.calls = 0
        self.last_prompt = ""

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.last_prompt = prompt
        if self.error is not None:
            exc = self.error() if callable(self.error) else self.error
            raise exc
        return SimpleNamespace(content=self.content)


def _make_state(env, model, *, enabled=True, retries=3, reasoning_blind=True,
                policy_extra="", tid="t1", proxy_thread=True, permissions=None):
    cfg = resolve_proxy_review({})
    cfg["enabled"] = enabled
    cfg["audit_log"] = str(env.audit)
    cfg["retries"] = retries
    cfg["reasoning_blind"] = reasoning_blind
    cfg["policy_extra"] = policy_extra
    io, state = build_permission_interrupts(
        permissions or {},
        project_root=env.tmp,
        proxy_review=cfg,
        proxy_review_model=model,
    )
    state["thread_id"] = tid
    if proxy_thread:
        proxy_on(state, tid)
    return io, state


def _req(tool, args, *, human=None, tool_results=()):
    messages = [{"role": "tool", "content": t} for t in tool_results]
    if human is not None:
        messages.append({"role": "human", "content": human})
    return SimpleNamespace(
        tool_call={"name": tool, "args": args, "id": "tc1"},
        state={"messages": messages},
    )


def _audit_lines(audit_path):
    try:
        text = Path(audit_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]

# ---------- review_outcome 裁决矩阵 ----------

@pytest.mark.parametrize(
    ("risk", "auth", "narrow", "expect_allow"),
    [
        ("low", "low", False, True),
        ("medium", "low", False, True),
        ("high", "medium", True, True),
        ("high", "high", True, True),
        ("high", "critical", True, True),
        ("high", "low", True, False),
        ("high", "medium", False, False),
        ("critical", "critical", True, False),
        ("urgent", "high", True, False),
        ("", "", False, False),
        ("HIGH", "Critical", True, True),
    ],
)
def test_review_outcome_matrix(risk, auth, narrow, expect_allow):
    assert (pr.review_outcome(risk, auth, narrow) == "allow") is expect_allow


# ---------- scope_is_narrow 纯字符串判定 ----------

@pytest.mark.parametrize(
    ("tool", "args", "expect"),
    [
        ("write_file", {"file_path": "a/b.md", "content": "x"}, True),
        ("write_file", {"path": "a/b.md"}, True),
        ("write_file", {"file_path": ""}, False),
        ("write_file", {"file_path": "a/*.md"}, False),
        ("write_file", {"file_path": "a?[].md"}, False),
        ("write_file", {"file_path": "a.md,b.md"}, False),
        ("write_file", {"content": "x"}, False),
        ("edit_file", {"file_path": "a.md", "old_str": "x"}, True),
        ("edit_file", {"file_path": "a.md", "pattern": "x"}, True),
        ("edit_file", {"path": "a.md", "pattern": "abc"}, True),
        ("edit_file", {"file_path": "a.md", "old_str": "  "}, False),
        ("edit_file", {"file_path": "a.md"}, False),
        ("delete", {"path": "a.md"}, True),
        ("delete", {"file_path": "a.md"}, True),
        ("delete", {"path": "a/*.md"}, False),
        ("delete", {"path": ""}, False),
        ("delete", {}, False),
        ("execute", {"command": "echo hi"}, False),
        ("read_file", {"file_path": "a.md"}, False),
        ("write_file", "not-a-dict", False),
    ],
)
def test_scope_is_narrow_matrix(tool, args, expect):
    assert pr.scope_is_narrow(tool, args) is expect


# ---------- 指纹幂等缓存 ----------

def test_cache_miss_then_hit(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    req = _req("execute", _GATE_ARGS["execute"])
    assert pr.proxy_review_upgrade(state, "execute", _GATE_ARGS["execute"], req) is True
    assert model.calls == 1
    lines = _audit_lines(env.audit)
    assert len(lines) == 1
    last = state[PROXY_REVIEW_LAST_KEY]
    assert set(last) == {
        "ts", "tool", "outcome", "risk", "authorization",
        "rationale", "note", "fingerprint", "thread_id", "cache_hit",
    }
    assert last["cache_hit"] is False
    assert len(last["fingerprint"]) == 12
    assert last["thread_id"] == "t1"
    assert last["note"] == ""
    # 缓存命中：同参数第二次 → 零模型调用、零审计、LAST 标 cache_hit
    assert pr.proxy_review_upgrade(state, "execute", _GATE_ARGS["execute"], req) is True
    assert model.calls == 1
    assert len(_audit_lines(env.audit)) == 1
    assert state[PROXY_REVIEW_LAST_KEY]["cache_hit"] is True


def test_cache_lru_eviction(monkeypatch):
    monkeypatch.setattr(pr, "_CACHE_LIMIT", 2)
    pr._cache_store("f1", {"outcome": "allow"})
    pr._cache_store("f2", {"outcome": "allow"})
    pr._cache_store("f3", {"outcome": "allow"})
    assert set(pr._REVIEW_CACHE) == {"f2", "f3"}


def test_cache_clear_reinvokes(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["execute"]
    assert pr.proxy_review_upgrade(state, "execute", args, _req("execute", args)) is True
    pr.clear_review_cache()
    assert pr.proxy_review_upgrade(state, "execute", args, _req("execute", args)) is True
    assert model.calls == 2
    assert len(_audit_lines(env.audit)) == 2




# ---------- fail-closed：审查失败 / 坏 JSON / 高危裁决 ----------

def test_model_exception_fails_closed(env):
    model = FakeModel(error=RuntimeError("boom"))
    io, state = _make_state(env, model, retries=2)
    args = _GATE_ARGS["execute"]
    assert pr.proxy_review_upgrade(state, "execute", args, _req("execute", args)) is False
    assert model.calls == 2
    last = state[PROXY_REVIEW_LAST_KEY]
    assert last["outcome"] == "ask"
    assert "RuntimeError" in last["note"]
    assert last["risk"] == ""
    assert len(_audit_lines(env.audit)) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "[1, 2, 3]",
        '{"risk": "low"}',
        '{"risk": "urgent", "authorization": "low"}',
        '[{"risk": "low"}]',
    ],
)
def test_bad_json_fails_closed(env, bad):
    model = FakeModel(content=bad)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["write_file"]
    assert pr.proxy_review_upgrade(state, "write_file", args, _req("write_file", args)) is False
    assert model.calls == 1
    last = state[PROXY_REVIEW_LAST_KEY]
    assert last["outcome"] == "ask"
    assert "JSON 解析失败" in last["note"]
    assert len(_audit_lines(env.audit)) == 1


def test_critical_verdict_on_write_fails_closed(env):
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["write_file"]
    assert pr.proxy_review_upgrade(state, "write_file", args, _req("write_file", args)) is False
    assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "deny"


def test_high_risk_execute_never_narrow_fails_closed(env):
    high_json = '{"risk": "high", "authorization": "critical", "rationale": "r"}'
    model = FakeModel(content=high_json)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["execute"]
    # execute 永远 narrow=False → high 裁决 → ask
    assert pr.proxy_review_upgrade(state, "execute", args, _req("execute", args)) is False


# ---------- 正交性：非 ask 路径零模型调用 ----------

def test_yolo_short_circuit_zero_model(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    yolo_on(state, "t1")
    req = _req("execute", _GATE_ARGS["execute"])
    assert io["execute"]["when"](req) is False
    assert model.calls == 0
    assert state[PROXY_REVIEW_LAST_KEY] == {}


def test_proxy_floor_inside_root_zero_model(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    req = _req("write_file", {"file_path": "notes.md", "content": "x"})
    # 项目根内写 → 地板直接放行，不到裁决层
    assert io["write_file"]["when"](req) is False
    assert model.calls == 0
    assert state[PROXY_REVIEW_LAST_KEY] == {}


def test_explicit_deny_no_when(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model, permissions={"execute": "deny"})
    assert io["execute"] is False


def test_heuristic_readonly_zero_model(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model, permissions={"heuristics": True})
    req = _req("execute", {"command": "git status"})
    assert io["execute"]["when"](req) is False
    assert model.calls == 0
    assert state[PROXY_REVIEW_LAST_KEY] == {}


def test_proxy_thread_off_gate_inert(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model, proxy_thread=False)
    args = _GATE_ARGS["execute"]
    assert io["execute"]["when"](_req("execute", args)) is True
    assert model.calls == 0
    assert state[PROXY_REVIEW_LAST_KEY] == {}


# ---------- when 谓词端到端 ----------

def test_when_low_verdict_auto_allows(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["execute"]
    assert io["execute"]["when"](_req("execute", args)) is False
    assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "allow"
    assert len(_audit_lines(env.audit)) == 1


def test_when_critical_verdict_keeps_interrupt(env):
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["delete"]
    assert io["delete"]["when"](_req("delete", args)) is True
    assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "deny"
    assert len(_audit_lines(env.audit)) == 1


# ---------- inert 门：enabled=False / 无模型 ----------

def test_enabled_false_inert(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model, enabled=False)
    args = _GATE_ARGS["execute"]
    assert io["execute"]["when"](_req("execute", args)) is True
    assert model.calls == 0
    assert state[PROXY_REVIEW_LAST_KEY] == {}


def test_no_model_inert(env):
    io, state = _make_state(env, None)
    args = _GATE_ARGS["execute"]
    assert io["execute"]["when"](_req("execute", args)) is True
    assert state[PROXY_REVIEW_LAST_KEY] == {}


# ---------- 提示词装配 ----------

def test_prompt_assembly_blind_default(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(
        env, model, reasoning_blind=True,
        policy_extra="只允许白名单命令",
    )
    root = Path(state["project_root"])
    (root / "AGENTS.md").write_text("# 项目约定\n#PROXY_REVIEW_AGENTS_MARKER#\n", encoding="utf-8")
    args = _GATE_ARGS["execute"]
    req = _req("execute", args, human="帮我检查依赖", tool_results=["done /tmp/out"])
    assert pr.proxy_review_upgrade(state, "execute", args, req) is True
    prompt = model.last_prompt
    assert "你是权限审批系统的 LLM 裁决层（替我审批）" in prompt
    assert "### 当前工具调用" in prompt
    assert "工具: execute" in prompt
    assert "curl http://example.com" in prompt
    assert "### 用户最近消息（意图上下文）" in prompt
    assert "帮我检查依赖" in prompt
    assert "### 项目约定（AGENTS.md 摘要）" in prompt
    assert "#PROXY_REVIEW_AGENTS_MARKER#" in prompt
    assert "### 额外策略（用户自定义）" in prompt
    assert "只允许白名单命令" in prompt
    assert "判定口径" in prompt
    assert "只输出一个 JSON 对象" in prompt
    # reasoning_blind=True：最近工具结果不入提示词
    assert "### 最近工具执行结果（补充）" not in prompt
    assert "/tmp/out" not in prompt


def test_prompt_not_blind_includes_tool_result(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model, reasoning_blind=False)
    args = _GATE_ARGS["execute"]
    req = _req("execute", args, tool_results=["done /tmp/out"])
    assert pr.proxy_review_upgrade(state, "execute", args, req) is True
    prompt = model.last_prompt
    assert "### 最近工具执行结果（补充）" in prompt
    assert "/tmp/out" in prompt
    # 无 human 消息 → 意图上下文节缺席
    assert "### 用户最近消息（意图上下文）" not in prompt


def test_prompt_user_text_capped(env):
    model = FakeModel(content=ALLOW_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["execute"]
    req = _req("execute", args, human="x" * 3000)
    pr.proxy_review_upgrade(state, "execute", args, req)
    prompt = model.last_prompt
    assert "x" * 2000 in prompt
    assert "x" * 2001 not in prompt


# ---------- #20: 呈现层 review_last_record（state 键读取契约） ----------

def test_review_last_record_hit_and_copy():
    rec_src = {"tool": "execute", "thread_id": "t1", "outcome": "allow", "rationale": "低危只读"}
    state = {PROXY_REVIEW_LAST_KEY: rec_src}
    for tid in ("t1", ""):
        rec = pr.review_last_record(state, "execute", tid)
        assert rec == rec_src
        assert rec is not rec_src
        # 浅拷贝：改调用方副本不影响共享 state 里的记录
        rec["outcome"] = "mutated"
        assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "allow"


@pytest.mark.parametrize(("tool", "tid"), [("write_file", "t1"), ("execute", "t2")])
def test_review_last_record_mismatch(tool, tid):
    rec = {"tool": "execute", "thread_id": "t1", "outcome": "allow"}
    state = {PROXY_REVIEW_LAST_KEY: rec}
    # write_file != execute（工具不匹配）；execute+t2 != rec.thread_id t1（跨线程）
    assert pr.review_last_record(state, tool, tid) is None


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {PROXY_REVIEW_LAST_KEY: {}},
        {PROXY_REVIEW_LAST_KEY: "not-a-dict"},
        {PROXY_REVIEW_LAST_KEY: None},
        {PROXY_REVIEW_LAST_KEY: 42},
        {"other": 1},
    ],
)
def test_review_last_record_defensive(state):
    assert pr.review_last_record(state, "execute", "t1") is None


# outcome=ask 时的回落注记（#20/#21）：critical → deny 不再回落 ask（#21），high / 越界注记保留
@pytest.mark.parametrize(
    ("tool", "verdict_json", "check"),
    [
        (
            "execute",
            '{"risk": "high", "authorization": "critical", "rationale": "r"}',
            lambda n: n == "high 风险未收窄范围，回落人工审批",
        ),
        # 枚举越界 → _decide fail-closed 注记（非成功回落三分支，三分支 note 为空时才有）
        (
            "write_file",
            '{"risk": "urgent", "authorization": "low", "rationale": "r"}',
            lambda n: n.startswith("JSON 解析失败") and "越界" in n,
        ),
    ],
)
def test_outcome_ask_fallback_note(env, tool, verdict_json, check):
    model = FakeModel(content=verdict_json)
    io, state = _make_state(env, model)
    args = _GATE_ARGS[tool]
    assert pr.proxy_review_upgrade(state, tool, args, _req(tool, args)) is False
    rec = state[PROXY_REVIEW_LAST_KEY]
    assert rec["outcome"] == "ask"
    assert check(rec["note"])



# ---------- #21：critical → deny（模型否决）/ 一次性覆盖预算 / 线程级断路器 ----------


def test_critical_deny_with_budget(env):
    """#21：critical 裁决 → 升级不成立，LAST 记录留 risk/rationale，note 空，审计 1 行。"""
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["delete"]
    assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    assert model.calls == 1
    rec = state[PROXY_REVIEW_LAST_KEY]
    assert rec["outcome"] == "deny"
    assert rec["risk"] == "critical"
    assert rec["rationale"] == "不可逆"
    assert rec["note"] == ""
    assert rec["cache_hit"] is False
    assert len(_audit_lines(env.audit)) == 1


def test_budget_exhausted_downgrades_to_ask(env):
    """#21：覆盖预算耗尽（t1 已用 10 条）→ deny 降级 ask + 回落注记。"""
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_OVERRIDES_KEY] = {"t1": 10}
    args = _GATE_ARGS["delete"]
    assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    rec = state[PROXY_REVIEW_LAST_KEY]
    assert rec["outcome"] == "ask"
    assert rec["note"] == "覆盖上限（10 条）已达，回落人工审批"
    assert model.calls == 1


def test_breaker_streak_three_consecutive_denies(env):
    """#21：连续 3 次 deny 触发断路器；再调不调模型/不写审计，回落 ask + 断路器注记。"""
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    for i in range(3):
        args = {"path": "d-%d.md" % i}
        assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    b = state[PROXY_REVIEW_BREAKERS_KEY]["t1"]
    assert b["tripped"] is True
    assert b["streak"] == 3
    args = {"path": "d-9.md"}
    assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    rec = state[PROXY_REVIEW_LAST_KEY]
    assert rec["outcome"] == "ask"
    assert "断路器已触发" in rec["note"]
    assert rec["breaker_tripped"] is True
    assert model.calls == 3
    assert len(_audit_lines(env.audit)) == 3


def test_breaker_window_trip_via_helper():
    """#21（交错）：窗口内 deny 达 10 次触发；allow 清零 streak 但占窗口名额。"""
    state = {}
    cfg = {"breaker": {"deny_streak": 3, "deny_in_window": 10, "window": 50}}
    for _ in range(9):
        pr._record_verdict_breaker(state, "t1", "deny", cfg)
        assert pr.breaker_tripped(state, "t1") is False
        pr._record_verdict_breaker(state, "t1", "allow", cfg)
    pr._record_verdict_breaker(state, "t1", "deny", cfg)
    rec = state[PROXY_REVIEW_BREAKERS_KEY]["t1"]
    assert rec["tripped"] is True
    assert rec["streak"] == 1
    assert rec["window"].count("deny") == 10


def test_breaker_streak_reset_by_non_deny():
    """#21：deny、deny（streak 2）后 allow → streak 清零、窗口保留、不触发。"""
    state = {}
    cfg = {"breaker": {"deny_streak": 3, "deny_in_window": 10, "window": 50}}
    pr._record_verdict_breaker(state, "t1", "deny", cfg)
    pr._record_verdict_breaker(state, "t1", "deny", cfg)
    rec = state[PROXY_REVIEW_BREAKERS_KEY]["t1"]
    assert rec["streak"] == 2
    assert rec["tripped"] is False
    pr._record_verdict_breaker(state, "t1", "allow", cfg)
    rec = state[PROXY_REVIEW_BREAKERS_KEY]["t1"]
    assert rec["streak"] == 0
    assert rec["window"].count("deny") == 2
    assert rec["tripped"] is False


def test_cache_hit_does_not_advance_breaker(env):
    """#21：同参缓存命中不是新裁决 → 断路器不推进，模型只调 1 次。"""
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    args = _GATE_ARGS["delete"]
    for _ in range(2):
        assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    assert model.calls == 1
    rec = state[PROXY_REVIEW_LAST_KEY]
    assert rec["outcome"] == "deny"
    assert rec["cache_hit"] is True
    b = state[PROXY_REVIEW_BREAKERS_KEY]["t1"]
    assert b["streak"] == 1
    assert b["tripped"] is False


def test_override_budget_math_and_isolation():
    """#21：record_override 返回已用次数（1-based）；预算 = 上限 - 已用；线程隔离；None-state 兜底。"""
    state = {}
    assert pr.override_budget_left(state, "t1") == pr.OVERRIDE_CAP
    for i in range(10):
        assert pr.record_override(state, "t1") == i + 1
    assert pr.override_budget_left(state, "t1") == 0
    assert pr.record_override(state, "t1") == pr.OVERRIDE_CAP + 1
    assert state[PROXY_REVIEW_OVERRIDES_KEY] == {"t1": pr.OVERRIDE_CAP + 1}
    assert pr.override_budget_left(state, "t2") == pr.OVERRIDE_CAP
    assert pr.override_budget_left(None, "t1") == pr.OVERRIDE_CAP
    assert pr.record_override(None, "t1") == 0


def test_proxy_review_note_cases(env):
    """#21：proxy_review_note 四态：无记录 / deny+余量（hint 开关）/ 预算耗尽 / ask 注记透传。"""
    model = FakeModel(content=CRITICAL_JSON)
    io, state = _make_state(env, model)
    assert pr.proxy_review_note(state, "delete", "t1") == (None, False)
    args = _GATE_ARGS["delete"]
    assert pr.proxy_review_upgrade(state, "delete", args, _req("delete", args)) is False
    assert pr.proxy_review_note(state, "delete", "t1", override_hint=True) == (
        "不可逆｜可一次性覆盖（本线程剩 10 次）",
        True,
    )
    assert pr.proxy_review_note(state, "delete", "t1") == ("不可逆", True)
    state[PROXY_REVIEW_OVERRIDES_KEY] = {"t1": 10}
    assert pr.proxy_review_note(state, "delete", "t1") == (None, False)
    state[PROXY_REVIEW_LAST_KEY] = {
        "tool": "execute",
        "thread_id": "t1",
        "outcome": "ask",
        "note": "high 风险未收窄范围，回落人工审批",
    }
    assert pr.proxy_review_note(state, "execute", "t1") == (
        "high 风险未收窄范围，回落人工审批",
        False,
    )

# ---------- #22 context_aware 有界只读探查 ----------


class SeqModel:
    """按序响应：首响应=一阶段裁决，次响应=二阶段（探查）裁决；越界取最后。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.prompts = []

    def invoke(self, prompt, **kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        return SimpleNamespace(
            content=self.responses[min(self.calls - 1, len(self.responses) - 1)]
        )


def _probe_req(msgs):
    return SimpleNamespace(
        tool_call={"name": "write_file", "args": _GATE_ARGS["write_file"], "id": "tc1"},
        state={"messages": msgs},
    )


def test_probe_loosens_ask_to_allow(env, monkeypatch):
    model = SeqModel([ASK_JSON, ALLOW_JSON])
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_KEY]["context_aware"] = True
    monkeypatch.setattr(pr, "_diff_summary", lambda *a, **k: " src/x.py | 2 +-" + chr(10))
    req = _probe_req(
        [
            {"role": "human", "content": "更早指令: 改 readme"},
            {"role": "tool", "content": "done"},
            {"role": "human", "content": "最近指令: 写 outside.md"},
        ]
    )
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is True
    assert model.calls == 2
    last = state[PROXY_REVIEW_LAST_KEY]
    assert last["outcome"] == "allow"
    assert last["probed"] is True
    assert "只读探查" not in model.prompts[0]
    p1 = model.prompts[1]
    assert "更早用户消息（只读探查）" in p1
    assert "更早指令: 改 readme" in p1
    assert "文件变更摘要（只读探查，git diff --stat）" in p1
    assert " src/x.py" in p1
    assert p1.count("最近指令: 写 outside.md") == 1


def test_probe_disabled_by_default(env):
    model = FakeModel(ASK_JSON)
    io, state = _make_state(env, model)
    req = _req("write_file", _GATE_ARGS["write_file"])
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is False
    assert model.calls == 1
    last = state[PROXY_REVIEW_LAST_KEY]
    assert "probed" not in last
    assert last["outcome"] == "ask"


def test_probe_only_loosens_not_tighten(env):
    model = SeqModel([ASK_JSON, CRITICAL_JSON])
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_KEY]["context_aware"] = True
    req = _req("write_file", _GATE_ARGS["write_file"])
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is False
    assert model.calls == 2
    last = state[PROXY_REVIEW_LAST_KEY]
    assert last["probed"] is True
    assert last["outcome"] == "ask"
    assert last["note"].endswith("（只读探查未采纳）")


def test_probe_stage2_fail_closed(env):
    model = SeqModel([ASK_JSON, "not json"])
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_KEY]["context_aware"] = True
    req = _req("write_file", _GATE_ARGS["write_file"])
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is False
    assert model.calls == 2
    last = state[PROXY_REVIEW_LAST_KEY]
    assert last["probed"] is True
    assert last["outcome"] == "ask"
    assert last["note"].endswith("（只读探查未采纳）")


def test_diff_summary_bounded_and_fail_safe(env, monkeypatch):
    assert pr._diff_summary("") == ""
    assert pr._diff_summary(None) == ""

    def _raise(*a, **k):
        raise TimeoutError("timeout")

    monkeypatch.setattr(pr.subprocess, "run", _raise)
    assert pr._diff_summary(env.tmp) == ""

    big = ("a| 1 +-" + chr(10)) * 2000

    def _fake_ok(cmd, **kwargs):
        return SimpleNamespace(stdout=big, stderr="", returncode=0)

    monkeypatch.setattr(pr.subprocess, "run", _fake_ok)
    assert len(pr._diff_summary(env.tmp)) == pr._DIFF_CAP

    def _fake_staged(cmd, **kwargs):
        return SimpleNamespace(
            stdout="b| 1 +" + chr(10) if "--staged" in cmd else "", stderr="", returncode=0
        )

    monkeypatch.setattr(pr.subprocess, "run", _fake_staged)
    out = pr._diff_summary(env.tmp)
    assert "[staged]" in out and "b| 1 +" in out


def test_probe_user_history_bounded(env, monkeypatch):
    model = SeqModel([ASK_JSON, ALLOW_JSON])
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_KEY]["context_aware"] = True
    monkeypatch.setattr(pr, "_diff_summary", lambda *a, **k: "")
    req = _probe_req([{"role": "human", "content": m} for m in ("m1", "m2", "m3", "m4", "m5")])
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is True
    p1 = model.prompts[1]
    assert "更早用户消息（只读探查）" in p1
    assert "m3" in p1 and "m4" in p1
    assert "m1" not in p1 and "m2" not in p1


def test_upgrade_no_probe_when_stage1_allow(env):
    model = SeqModel([ALLOW_JSON, ASK_JSON])
    io, state = _make_state(env, model)
    state[PROXY_REVIEW_KEY]["context_aware"] = True
    req = _req("write_file", _GATE_ARGS["write_file"])
    assert pr.proxy_review_upgrade(state, "write_file", _GATE_ARGS["write_file"], req) is True
    assert model.calls == 1
    assert "只读探查" not in model.prompts[0]
    last = state[PROXY_REVIEW_LAST_KEY]
    assert "probed" not in last
    assert last["outcome"] == "allow"

