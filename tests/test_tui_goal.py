"""#goal 05: TUI 自动续跑接线（turn finally 续跑决策入队 + 预算后置终态 + create_goal notify + [GOAL] sub_title + 续跑输入 dim 行）。"""
import os
import shutil
import uuid

import pytest

from src import goals
from src.streaming import TurnOutcome
from src.tui_turn import TurnPresenter
from tests.test_tui import FakeAgent


def _turn(ok=True, outcome="complete", tools=1):
    return TurnOutcome(ok=ok, outcome=outcome, tool_calls_count=tools)


@pytest.fixture
def goal_store(monkeypatch):
    """goals.json 全局存储隔离：仓库根自建目录（tmp_path 禁用——pytest 基 temp WinError 5 中毒）。"""
    base = os.path.join(os.getcwd(), ".scratch", "goal-tui-tmp", str(uuid.uuid4()))
    os.makedirs(base, exist_ok=True)
    from pathlib import Path

    target = Path(base) / "goals.json"
    monkeypatch.setattr(goals, "goals_path", lambda: target)
    try:
        yield Path(base)
    finally:
        shutil.rmtree(base, ignore_errors=True)


class _FakeLog:
    def __init__(self):
        self.written = []

    def write(self, t):
        self.written.append(t)

    def write_tool_entry(self, collapsed, expanded):
        self.written.append(collapsed)


class _Queue:
    """JumpInRegistry 最小桩：push 记队列、pop_first 弹队首。"""

    def __init__(self):
        self.items = {}

    def push(self, tid, text):
        self.items.setdefault(tid, []).append(text)
        return len(self.items[tid])

    def pop_first(self, tid):
        q = self.items.get(tid)
        return q.pop(0) if q else None


class _StubApp:
    def __init__(self, mode="act", tid="t-goal"):
        self.thread_id = tid
        self.permission_state = {"mode": mode}
        self._queue = _Queue()
        self.agent = None
        self.config = None
        self.log = _FakeLog()
        self.notifies = []
        self.releases = []
        self.sub_titles = 0
        self.incomplete = []

    def call_from_thread(self, fn, *args, **kw):
        return fn(*args, **kw)

    def query_one(self, sel, typ):
        return self.log

    def notify(self, msg, timeout=None, **kw):
        self.notifies.append((msg, timeout))

    def _release_turn_gate(self, tid):
        self.releases.append(tid)

    def _update_sub_title(self):
        self.sub_titles += 1

    def _on_turn_incomplete(self, tid):
        self.incomplete.append(tid)

    def _hide_ai_stream(self):
        pass

    def _hide_spinner_if_idle(self, tid):
        pass

    def _refresh_todos_panel(self):
        pass

    def _finalize_ai_stream(self, *a, **kw):
        pass

    def _workspace_root(self):
        return None


def _run_turn(monkeypatch, app, user_input, outcome_turn, mode=None):
    """构造 TurnPresenter 并驱动 run()（worker 桩 + run_agent_turn 桩）。"""
    monkeypatch.setattr("src.tui_turn.get_current_worker", lambda: None)
    monkeypatch.setattr(
        "src.tui_turn.streaming.run_agent_turn",
        lambda *a, **kw: outcome_turn,
    )
    p = TurnPresenter(app, user_input=user_input, checkpoint_id=None)
    p.run()
    return p


# ---------- ⑧ goal_input_label 正/负例 ----------


def test_goal_input_label_cases():
    assert goals.goal_input_label("[目标续跑 2/5] 自动续跑") == "目标续跑 2/5"
    assert goals.goal_input_label("[目标预算耗尽 5/5] 收尾") == "目标收尾 5/5"
    assert goals.goal_input_label("普通消息") is None
    assert goals.goal_input_label(None) is None
    assert goals.goal_input_label("[目标续跑 abc]") is None
    assert goals.goal_input_label("[目标 1/2]") is None


# ---------- ① 触发入队 ----------


def test_continuation_queued_when_active_with_tools(monkeypatch, goal_store):
    tid = "t-1"
    goals.goal_set(thread_id=tid, objective="修好 CI", max_turns=5)
    app = _StubApp(tid=tid)
    _run_turn(monkeypatch, app, "原始任务", _turn())
    q = app._queue.items.get(tid, [])
    assert len(q) == 1
    assert q[0].startswith("[目标续跑 1/5]")
    assert "修好 CI" in q[0]
    g = goals.goal_status(thread_id=tid)
    assert g.turns_used == 1
    assert g.status == goals.GOAL_ACTIVE


# ---------- ② 不触发矩阵 ----------


@pytest.mark.parametrize(
    "prepare,outcome,mode,tid,setup",
    [
        ("no_goal", "complete", "act", "t-nog", lambda: None),
        ("zero_tools", "complete", "act", "t-zt", lambda: None),
        ("cancel", "cancel", "act", "t-cx", lambda: None),
        ("abandon", "abandon", "act", "t-ab", lambda: None),
        ("plan", "complete", "plan", "t-pl", lambda: None),
        ("pending", "complete", "act", "t-pd", lambda: None),
        ("complete", "complete", "act", "t-cp", lambda: None),
        ("paused", "complete", "act", "t-pa", lambda: None),
        ("sched", "complete", "act", "sched-x", lambda: None),
    ],
    ids=[
        "no_goal", "zero_tools", "cancel", "abandon",
        "plan", "pending", "complete", "paused", "sched",
    ],
)
def test_no_continuation_matrix(monkeypatch, goal_store, prepare, outcome, mode, tid, setup):
    if prepare not in ("no_goal",):
        goals.goal_set(thread_id=tid, objective="o", max_turns=5)
    setup()
    if prepare == "complete":
        goals.goal_complete(thread_id=tid, audit_evidence="e")
    if prepare == "paused":
        goals.goal_pause(thread_id=tid)
    tools = 0 if prepare == "zero_tools" else 1
    app = _StubApp(mode=mode, tid=tid)
    if prepare == "pending":
        # pending 分支不走 _run_turn：手动构造同一 presenter 实例并驱动 run()
        # （_turn_incomplete_seen 标记与 finally 续跑判定必须落在同一实例）
        monkeypatch.setattr("src.tui_turn.get_current_worker", lambda: None)
        monkeypatch.setattr(
            "src.tui_turn.streaming.run_agent_turn",
            lambda *a, **kw: _turn(outcome=outcome, tools=tools),
        )
        p = TurnPresenter(app, user_input="任务", checkpoint_id=None)
        p.on_turn_incomplete()
        p.run()
    else:
        _run_turn(monkeypatch, app, "任务", _turn(outcome=outcome, tools=tools))
    assert app._queue.items.get(tid, []) == []
    g = goals.goal_status(thread_id=tid)
    if g is not None:
        assert g.turns_used == 0


# ---------- ③ budget 链 ----------


def test_budget_chain_marks_terminal_only_after_wrapup(monkeypatch, goal_store):
    tid = "t-bud"
    goals.goal_set(thread_id=tid, objective="o", max_turns=2)
    app = _StubApp(tid=tid)
    # 轮 1 → 续跑 1/2 入队
    _run_turn(monkeypatch, app, "任务", _turn())
    q = app._queue.items[tid]
    assert len(q) == 1 and q[0].startswith("[目标续跑 1/2]")
    # 轮 2（续跑输入）→ 预算耗尽 2/2 入队（收尾交接轮）
    _run_turn(monkeypatch, app, q.pop(0), _turn())
    q = app._queue.items[tid]
    assert len(q) == 1 and q[0].startswith("[目标预算耗尽 2/2]")
    assert goals.goal_status(thread_id=tid).status == goals.GOAL_ACTIVE  # 终态尚未标记
    # 轮 3（收尾交接输入）→ 该轮跑完后才后置 budget_limited；决策 none 不再入队
    _run_turn(monkeypatch, app, q.pop(0), _turn())
    g = goals.goal_status(thread_id=tid)
    assert g.status == goals.GOAL_BUDGET_LIMITED
    assert app._queue.items[tid] == []
    # 终态后任何正常轮不再续跑
    _run_turn(monkeypatch, app, "再来", _turn())
    assert app._queue.items[tid] == []


# ---------- ④ ok 状态行 label 后缀 ----------


def test_ok_status_line_label_suffix(monkeypatch, goal_store):
    tid = "t-lbl"
    goals.goal_set(thread_id=tid, objective="o", max_turns=10)
    app = _StubApp(tid=tid)
    _run_turn(monkeypatch, app, "[目标续跑 4/10] 自动续跑目标「o」。", _turn())
    last = [ln for ln in app.log.written if "▌ model" in ln][-1]
    assert "目标续跑 4/10" in last
    app2 = _StubApp(tid=tid)
    _run_turn(monkeypatch, app2, "[目标预算耗尽 4/10] 最后一续跑轮。", _turn())
    last2 = [ln for ln in app2.log.written if "▌ model" in ln][-1]
    assert "目标收尾 4/10" in last2
    app3 = _StubApp(tid=tid)
    _run_turn(monkeypatch, app3, "普通消息", _turn())
    last3 = [ln for ln in app3.log.written if "▌ model" in ln][-1]
    assert "目标" not in last3


# ---------- ⑤ 真实 app：[GOAL] sub_title 联动 ----------


@pytest.mark.asyncio
async def test_real_app_sub_title_goal_badge(monkeypatch, goal_store):
    from src.tui import JarvisApp
    from tests.test_tui import FakeAgent

    goals.goal_set(thread_id="default", objective="o", max_turns=5)
    app = JarvisApp(None, FakeAgent(reply="好"), {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        app._update_sub_title()
        assert "[GOAL] 0/5 进行中" in app.sub_title
        goals.goal_note_turn(thread_id="default")
        app._update_sub_title()
        assert "[GOAL] 1/5 进行中" in app.sub_title
        goals.goal_pause(thread_id="default")
        app._update_sub_title()
        assert "[GOAL] 1/5 已暂停" in app.sub_title
        goals.goal_resume(thread_id="default")
        goals.goal_complete(thread_id="default", audit_evidence="e")
        app._update_sub_title()
        assert "[GOAL] 1/5 已完成" in app.sub_title  # #goal 05: 终态也显示
        assert goals.GOAL_STATUS_CN[goals.GOAL_BUDGET_LIMITED] == "回合预算耗尽"
        await pilot.pause()


# ---------- ⑤b 真实 app：/goal status 命令回路（症状C回归：类型后状态行进对话区+徽章即时刷新） ----------


@pytest.mark.asyncio
async def test_real_app_goal_status_command_refreshes_badge(monkeypatch, goal_store):
    """#goal 05 症状C回归：输入 /goal status → 状态行写 #messages + sub_title 徽章刷新。

    修复前该命令无 dispatch 分支（无任何反应）；断言双信号：
    ①状态行进对话区（goal_text 文案）；②[GOAL] 徽章经 dispatch 后 _update_sub_title 刷新。
    """
    import asyncio

    from textual.widgets import RichLog

    from src.tui import JarvisApp
    from tests.test_tui import FakeAgent, _type_and_enter

    goals.goal_set(thread_id="default", objective="修好 CI", max_turns=5)
    goals.goal_note_turn(thread_id="default")
    app = JarvisApp(None, FakeAgent(reply="好"), {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        app._update_sub_title()
        await _type_and_enter(pilot, "/goal status")
        log = app.query_one("#messages", RichLog)
        joined = ""
        for _ in range(120):
            joined = "".join(ln.text for ln in log.lines)
            if "目标 [进行中] 1/5" in joined:
                break
            await asyncio.sleep(0.05)
        assert "目标 [进行中] 1/5：修好 CI" in joined, "/goal status 状态行应进对话区"
        assert "正在执行 /goal" in joined
        assert "[GOAL] 1/5 进行中" in app.sub_title, "dispatch 后徽章应刷新"
        await pilot.pause()


# ---------- ⑥ 真实 app：续跑输入渲染 dim 系统行 ----------


@pytest.mark.asyncio
async def test_real_app_goal_input_rendered_as_system_line(monkeypatch, goal_store):
    from src.tui import JarvisApp
    from tests.test_tui import FakeAgent

    goals.goal_set(thread_id="default", objective="o", max_turns=5)
    app = JarvisApp(None, FakeAgent(reply="好"), {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        app._handle_user_message("[目标续跑 0/5] 自动续跑目标「o」。")
        await pilot.pause()
        from textual.widgets import RichLog

        log = app.query_one("#messages", RichLog)
        joined = "".join(ln.text for ln in log.lines)
        assert "目标续跑 0/5…" in joined
        assert "[bold]你[/bold]" not in joined
        await pilot.pause()


# ---------- ⑦ create_goal notify ----------


def test_create_goal_notify_with_objective(monkeypatch, goal_store):
    app = _StubApp()
    p = TurnPresenter(app, user_input="hi", checkpoint_id=None)
    p.on_tool_call("create_goal", '{"objective": "x", "max_turns": 3}', False, None, 0)
    assert ("已设目标：x", 3) in app.notifies
    p.on_tool_call("create_goal", '{"objective": "y"}', True, "err", 0)
    assert len(app.notifies) == 1  # 失败调用不 notify


def test_create_goal_notify_non_json_fallback(monkeypatch, goal_store):
    app = _StubApp()
    p = TurnPresenter(app, user_input="hi", checkpoint_id=None)
    args = "objective" + "a" * 80
    p.on_tool_call("create_goal", args, False, None, 0)
    assert app.notifies[0][0] == "已设目标：" + args[:60]


# ---------- diagnosing-bugs /goal 修复：TUI create/resume 链重启 kick ----------


class _RecordingAgent(FakeAgent):
    """记录每次 stream_events 的输入（续跑 kick 到达模型层的断言面）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.recorded_inputs = []

    def stream_events(self, *args, **kwargs):
        self.recorded_inputs.append(args[0])
        return super().stream_events(*args, **kwargs)


def _kick_text(stream_input):
    """stream_events 首参 → 续跑 prompt 原文（str 原样；{'messages': [...]} 取首条 user content）。"""
    if isinstance(stream_input, dict):
        msgs = stream_input.get("messages") or []
        return str(msgs[-1].get("content") if msgs else "")
    return str(stream_input)


async def _wait_inputs(agent, predicate, timeout=6.0):
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    pytest.fail("等待超时：未观察到预期的 agent 输入序列")


@pytest.mark.asyncio
async def test_real_app_goal_create_kicks_continuation_turn(monkeypatch, goal_store):
    """"jarvis停了就停了"修复回归：TUI /goal create 后自动 kick 一条续跑轮。

    create 成功 → dispatch 后 goal_kick_prompt 命中 active 0/5 → _goal_kick 经
    门控队列重入 → FakeAgent 收到 [目标续跑 1/5] 作为新一轮输入（零新机制验证）。
    """
    from textual.widgets import RichLog

    from src.tui import JarvisApp
    from tests.test_tui import _type_and_enter

    agent = _RecordingAgent(reply="好")
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/goal create 修好 CI")
        log = app.query_one("#messages", RichLog)
        joined = ""
        import asyncio
        for _ in range(120):
            joined = "".join(ln.text for ln in log.lines)
            if "正在执行 /goal" in joined:
                break
            await asyncio.sleep(0.05)
        await _wait_inputs(agent, lambda: any("[目标续跑 1/5]" in _kick_text(i) for i in agent.recorded_inputs))
        kick = _kick_text([i for i in agent.recorded_inputs if "[目标续跑 1/5]" in _kick_text(i)][0])
        assert kick.startswith("[目标续跑 1/5]"), "kick 应为 continuation prompt 原文"
        assert "修好 CI" in kick


@pytest.mark.asyncio
async def test_real_app_goal_status_does_not_kick(monkeypatch, goal_store):
    """/goal status 是读类命令：只刷新状态行与徽章，不触发任何模型轮。"""
    import asyncio

    from textual.widgets import RichLog

    from src.tui import JarvisApp
    from tests.test_tui import _type_and_enter

    goals.goal_set(thread_id="default", objective="修好 CI", max_turns=5)
    agent = _RecordingAgent(reply="好")
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/goal status")
        log = app.query_one("#messages", RichLog)
        joined = ""
        for _ in range(120):
            joined = "".join(ln.text for ln in log.lines)
            if "目标 [进行中] 0/5" in joined:
                break
            await asyncio.sleep(0.05)
        assert "目标 [进行中] 0/5：修好 CI" in joined
        await asyncio.sleep(0.3)
        assert agent.recorded_inputs == [], "/goal status 不得 kick 新轮"


@pytest.mark.asyncio
async def test_real_app_goal_resume_kicks_continuation_turn(monkeypatch, goal_store):
    """/goal resume：paused → active 后 kick [目标续跑 N/5]（N=turns_used+1）。"""

    from src.tui import JarvisApp
    from tests.test_tui import _type_and_enter

    goals.goal_set(thread_id="default", objective="修好 CI", max_turns=5)
    goals.goal_note_turn(thread_id="default")
    goals.goal_pause(thread_id="default")
    agent = _RecordingAgent(reply="好")
    app = JarvisApp(None, agent, {"default": "ask", "tools": {}}, thread_id="default")
    async with app.run_test() as pilot:
        await _type_and_enter(pilot, "/goal resume")
        await _wait_inputs(agent, lambda: any("[目标续跑 2/5]" in _kick_text(i) for i in agent.recorded_inputs))
        kick = _kick_text([i for i in agent.recorded_inputs if "[目标续跑 2/5]" in _kick_text(i)][0])
        assert "自动续跑目标「修好 CI」" in kick
