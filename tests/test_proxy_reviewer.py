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
    PROXY_REVIEW_LAST_KEY,
    build_permission_interrupts,
    proxy_on,
    yolo_on,
)

ALLOW_JSON = '{"risk": "low", "authorization": "low", "rationale": "低危"}'
CRITICAL_JSON = '{"risk": "critical", "authorization": "critical", "rationale": "不可逆"}'

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
    assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "ask"


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
    assert state[PROXY_REVIEW_LAST_KEY]["outcome"] == "ask"
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


# outcome=ask 时的回落注记（#20）：critical/high 走成功回落三分支，枚举越界由 _decide 给出注记
@pytest.mark.parametrize(
    ("tool", "verdict_json", "check"),
    [
        ("delete", CRITICAL_JSON, lambda n: n == "critical 风险回落人工审批"),
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

