"""/side 侧边会话内核单测（side-chat 工单01）。

覆盖：
- open_side：terminal head fork / 悬挂 head 回退最近 terminal / 空会话拒 /
  已在 side 拒 / 已有 side 拒；只读由 side 成员驱动 + 状态登记（主线模式不受影响）
- close_side：关闭 = 删除（delete_session 第三参=主线 tid，不误触发「删当前则新建」、
  不误删主线；回主线，主线模式全程未动）/ 非 side 拒
- side_parent_status 三态
- dispatch_command /side 分支（开 / 关（=删除）/ --discard 遗留别名 / 非法子参 / 权限层缺失）
- SideTaskGuardMiddleware：side 内拦 task+execute / 非 side 放行 / close 即解除（零重建）
- 权限层 state 键齐备（build_permission_interrupts 装 side_threads/side_parents）

无磁盘依赖、不用 tmp_path（本机 WinError 5 纪律）；close 路径 monkeypatch
commands.delete_session 记录调用，不触 inbox/time_travel 落盘。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src import commands
from src.permissions import (
    SIDE_PARENTS_KEY,
    SIDE_THREADS_KEY,
    SideTaskGuardMiddleware,
    build_permission_interrupts,
    side_active,
    side_close,
    side_open,
    side_parent,
)
from src.tool_call import ToolCallView


class _Head:
    def __init__(self, messages, next_=None, config=None):
        self.values = {"messages": list(messages)}
        self.next = next_
        self.config = config or {"configurable": {"thread_id": "t-main"}}


class _SideAgent:
    """fake agent：主线 t-main；threads 按线程记录 fork/边界 写入。

    pending=True 时 head.next 非空（HITL 悬挂），get_state_history 模拟
    append-only 日志：[悬挂 head, 最近 terminal]。
    """

    def __init__(self, main_msgs, pending=False, terminal_msgs=None):
        self.main_msgs = list(main_msgs)
        self.pending = pending
        self.terminal_msgs = list(terminal_msgs if terminal_msgs is not None else main_msgs)
        self.threads: dict = {}

    def get_state(self, config):
        tid = config["configurable"]["thread_id"]
        if tid == "t-main":
            return _Head(
                self.main_msgs,
                next_="model" if self.pending else None,
                config={"configurable": {"thread_id": "t-main"}},
            )
        return _Head(
            self.threads.get(tid, []),
            next_=None,
            config={"configurable": {"thread_id": tid}},
        )

    def get_state_history(self, config=None):
        if config["configurable"]["thread_id"] != "t-main":
            return []
        head = _Head(
            self.main_msgs,
            next_="model" if self.pending else None,
            config={"configurable": {"thread_id": "t-main"}},
        )
        if self.pending:
            terminal = _Head(
                self.terminal_msgs,
                next_=None,
                config={"configurable": {"thread_id": "t-main"}},
            )
            return [head, terminal]
        return [head]

    def update_state(self, config, values=None, as_node=None):
        """模拟真实 LangGraph：写入 config 里的 thread_id、原样返回该 tid（不产生新
        thread）；新 thread 首写 = 历史全量继承；已有 thread = add_messages 语义
        （按 id 替换，无 id 追加）。"""
        tid = config["configurable"]["thread_id"]
        msgs = list((values or {}).get("messages", []))
        existing = self.threads.get(tid)
        if existing is None:
            self.threads[tid] = list(msgs)
            return {"configurable": {"thread_id": tid}, "checkpoint_id": "cp-fork"}
        by_id = {}
        for m in msgs:
            mid = getattr(m, "id", None)
            if mid:
                by_id[mid] = m
        merged = [by_id.get(getattr(m, "id", None), m) for m in existing]
        merged.extend(m for m in msgs if getattr(m, "id", None) is None)
        self.threads[tid] = merged
        return {"configurable": {"thread_id": tid}, "checkpoint_id": "cp-upd"}


def _msgs():
    return [
        HumanMessage("问题 1", id="m1"),
        AIMessage("回答 1", id="a1"),
        HumanMessage("问题 2", id="m2"),
        AIMessage("回答 2", id="a2"),
    ]


# ---------------------------------------------------------------- open_side


def test_open_side_forks_terminal_head():
    agent = _SideAgent(_msgs())
    state = {}
    text, new_tid = commands.open_side(agent, "t-main", state)
    # 显式新 tid（真实 LangGraph 的 update_state 不「产生」新 thread）
    assert new_tid.startswith("side-") and new_tid != "t-main"
    assert "已开 side 会话" in text
    forked = agent.threads[new_tid]
    # boundary SystemMessage 置 0 位（网关要求 System 必须在开头），其后为继承主线历史
    assert isinstance(forked[0], SystemMessage)
    assert "t-main" in forked[0].content
    assert [m.id for m in forked[1:5]] == ["m1", "a1", "m2", "a2"]
    assert "t-main" not in agent.threads  # 主线未被写入
    # 状态登记（只读由 side 成员驱动；不碰主线 mode 键，对标 codex 隔离）
    assert side_active(state, new_tid)
    assert side_parent(state, new_tid) == "t-main"
    assert "mode" not in state


def test_open_side_keeps_mainline_plan_mode():
    agent = _SideAgent(_msgs())
    state = {"mode": "plan"}  # 主线处于 plan
    _, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid.startswith("side-") and new_tid != "t-main"
    # 开 side 不碰主线模式键（side 隔离，对标 codex）
    assert state["mode"] == "plan"
    from src.plan_mode import effective_mode

    assert effective_mode(state, new_tid) == "plan"
    assert effective_mode(state, "t-main") == "plan"


def test_open_side_pending_head_falls_back_to_terminal():
    pending_ai = AIMessage(
        "需要查看文件",
        id="a4",
        tool_calls=[{"name": "read_file", "args": {"path": "/workspace/a.py"}, "id": "tc1"}],
    )
    head = _msgs() + [HumanMessage("问题 4", id="m4"), pending_ai]
    agent = _SideAgent(head, pending=True, terminal_msgs=_msgs())
    state = {}
    text, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid.startswith("side-") and new_tid != "t-main"
    forked = agent.threads[new_tid]
    # 悬挂那一轮（含 pending tool_call）不带进 side
    assert all(m.id not in ("m4", "a4") for m in forked)
    assert isinstance(forked[0], SystemMessage)  # boundary 置 0 位
    assert [m.id for m in forked[1:5]] == ["m1", "a1", "m2", "a2"]


def test_open_side_boundary_first_when_main_compacted():
    """主线已 compact（历史 0 位是 compact 摘要 SystemMessage）：side 开出来后
    boundary 置 0 位、compact 摘要 System 紧随其后，更后不再出现 System；
    wire 恰好一个 System 位于 0 位的网关硬规则由 SystemHeadMiddleware
    调用时合并满足（见 tests/test_system_head.py 与下方集成断言）。"""
    main = [
        SystemMessage("[compact] 早前对话摘要：讨论了 X", id="c1"),
        HumanMessage("问题 1", id="m1"),
        AIMessage("回答 1", id="a1"),
    ]
    agent = _SideAgent(main)
    state = {}
    text, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid.startswith("side-")
    forked = agent.threads[new_tid]
    # boundary 0 位，compact 摘要 System 1 位；2 位起不得再出现 System
    assert isinstance(forked[0], SystemMessage) and "side" in forked[0].content
    assert forked[1].id == "c1" and isinstance(forked[1], SystemMessage)
    assert [m.id for m in forked[2:4]] == ["m1", "a1"]
    assert not any(isinstance(m, SystemMessage) for m in forked[2:])



def test_side_storage_form_merges_to_single_system_head():
    """v1 存储形式 [S(boundary), 继承历史] + 请求级主 agent prompt：
    SystemHeadMiddleware 调用时合并后，wire 恰好一个 System 在 0 位
    （文本 = 主 agent prompt + boundary 按序拼接），历史形式不变。"""
    from langchain.agents.middleware.types import ModelRequest

    from src.system_head import SystemHeadMiddleware

    agent = _SideAgent(_msgs())
    state = {}
    _, new_tid = commands.open_side(agent, "t-main", state)
    history = agent.threads[new_tid]
    assert isinstance(history[0], SystemMessage)  # boundary 存储形式 0 位

    req = ModelRequest(
        model=None,
        messages=list(history),
        system_message=SystemMessage(content="主 agent prompt"),
    )
    captured = []
    SystemHeadMiddleware().wrap_model_call(req, lambda r: captured.append(r) or "ok")
    out = captured[0]

    # wire 恰好一个 System（请求级头部），消息列表不再含 System
    assert out.system_message is not None
    assert "主 agent prompt" in out.system_message.content
    assert "side" in out.system_message.content
    assert not any(isinstance(m, SystemMessage) for m in out.messages)
    assert [m.id for m in out.messages] == ["m1", "a1", "m2", "a2"]
    # 存储形式未被中间件改动
    assert isinstance(agent.threads[new_tid][0], SystemMessage)


def test_open_side_rejects_blank_conversation():
    agent = _SideAgent([])
    state = {}
    text, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid is None
    assert "空会话无法开侧边会话" in text
    assert "mode" not in state
    assert "mode_before_side" not in state


def test_open_side_rejects_already_in_side():
    agent = _SideAgent(_msgs())
    state = {"side_threads": {"t-main"}, "side_parents": {"t-main": "other"}}
    text, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid is None
    assert "已在 side 会话" in text


def test_open_side_rejects_existing_side():
    agent = _SideAgent(_msgs())
    state = {"side_threads": {"side-x"}, "side_parents": {"side-x": "other"}}
    text, new_tid = commands.open_side(agent, "t-main", state)
    assert new_tid is None
    assert "已有 side 会话" in text


# ---------------------------------------------------------------- close_side


def _side_state():
    return {
        SIDE_THREADS_KEY: {"t-side"},
        SIDE_PARENTS_KEY: {"t-side": "t-main"},
    }


def test_close_side_deletes_session(monkeypatch):
    agent = _SideAgent(_msgs())
    state = _side_state()
    calls = []

    def _delete(a, target, current):
        calls.append((target, current))
        return f"已删除会话 {target}", None

    monkeypatch.setattr(commands, "delete_session", _delete)
    text, parent = commands.close_side(agent, "t-side", state)
    # 关闭 = 删除：第三参 = 主线 tid，不触发「删当前则新建」、不误删主线
    assert calls == [("t-side", "t-main")]
    assert parent == "t-main"
    assert "已删除 side 会话并返回主线 t-main" in text
    assert not side_active(state, "t-side")
    assert side_parent(state, "t-side") is None
    assert "mode" not in state
    assert "mode_before_side" not in state


def test_close_side_does_not_touch_mainline_mode(monkeypatch):
    agent = _SideAgent(_msgs())
    state = _side_state()
    state["mode"] = "plan"  # 主线处于 plan（模拟 Tab 全局切换）
    monkeypatch.setattr(
        commands, "delete_session",
        lambda a, target, current: (f"已删除会话 {target}", None),
    )
    _, _ = commands.close_side(agent, "t-side", state)
    # close 不碰主线模式键（side 隔离，对标 codex）
    assert state["mode"] == "plan"


def test_close_side_rejects_non_side():
    agent = _SideAgent(_msgs())
    text, parent = commands.close_side(agent, "t-main", {})
    assert parent is None
    assert "当前不在 side 会话" in text


# ------------------------------------------------------------ status / helpers


def test_side_parent_status_three_states():
    terminal = _SideAgent(_msgs())
    assert commands.side_parent_status(terminal, "t-main", {}) == "主线已结束"
    pending = _SideAgent(_msgs() + [HumanMessage("问题 4", id="m4")], pending=True)
    assert commands.side_parent_status(pending, "t-main", {}) == "主线进行中/待审批"

    class _Boom:
        def get_state(self, config):
            raise RuntimeError("boom")

    assert commands.side_parent_status(_Boom(), "t-main", {}) == "主线状态未知"


def test_side_state_helpers_idempotent():
    state = {}
    side_open(state, "s1", "m1")
    side_open(state, "s1", "m1")  # 幂等
    assert side_active(state, "s1")
    assert side_parent(state, "s1") == "m1"
    side_open(state, "", "m1")  # 空 id no-op
    assert not side_active(state, "")
    side_close(state, "s1")
    side_close(state, "s1")  # 缺失不报错
    assert not side_active(state, "s1")
    assert side_parent(state, "s1") is None
    # 旧引用防御：缺键 state 不崩
    assert not side_active({}, "s1")
    assert side_parent({}, "s1") is None


def test_permission_state_carries_side_keys():
    _, state = build_permission_interrupts(None)
    assert state.get(SIDE_THREADS_KEY) == set()
    assert state.get(SIDE_PARENTS_KEY) == {}


# ----------------------------------------------------------------- dispatch


def test_dispatch_side_open_and_close_roundtrip(monkeypatch):
    agent = _SideAgent(_msgs())
    state = {}
    calls = []

    def _delete(a, target, current):
        calls.append((target, current))
        return f"已删除会话 {target}", None

    monkeypatch.setattr(commands, "delete_session", _delete)
    text, new_tid, replay = commands.dispatch_command(agent, "t-main", "/side", permission_state=state)
    assert replay is None
    assert new_tid.startswith("side-") and new_tid != "t-main"
    assert "已开 side 会话" in text
    # 主线不被 side 写入
    assert "t-main" not in agent.threads
    text, closed, replay = commands.dispatch_command(agent, new_tid, "/side close", permission_state=state)
    assert closed == "t-main"  # close 回主线
    # close = 删除
    assert calls == [(new_tid, "t-main")]
    assert "已删除 side 会话并返回主线 t-main" in text
    assert not side_active(state, new_tid)


def test_dispatch_side_close_discard_legacy_alias(monkeypatch):
    agent = _SideAgent(_msgs())
    state = {}
    _, new_tid, _ = commands.dispatch_command(agent, "t-main", "/side", permission_state=state)
    assert new_tid.startswith("side-") and new_tid != "t-main"
    calls = []

    def _delete(a, target, current):
        calls.append((target, current))
        return f"已删除会话 {target}", None

    monkeypatch.setattr(commands, "delete_session", _delete)
    text, closed, replay = commands.dispatch_command(
        agent, new_tid, "/side close --discard", permission_state=state
    )
    assert calls == [(new_tid, "t-main")]
    assert closed == "t-main"
    assert "已删除 side 会话并返回主线 t-main" in text
    assert replay is None


def test_dispatch_side_bad_subarg_usage():
    text, new_tid, replay = commands.dispatch_command(
        _SideAgent(_msgs()), "t-main", "/side foo", permission_state={}
    )
    assert text == "用法: /side | /side close（关闭即删除 side 会话）"
    assert new_tid is None
    assert replay is None


def test_dispatch_side_without_permission_layer():
    text, new_tid, replay = commands.dispatch_command(_SideAgent(_msgs()), "t-main", "/side")
    assert "side 会话不可用（权限层未初始化）" in text
    assert new_tid is None


# ------------------------------------------------------------ task guard


def test_side_task_guard_blocks_task_in_side():
    state = {
        "thread_id": "t-side",
        SIDE_THREADS_KEY: {"t-side"},
        SIDE_PARENTS_KEY: {"t-side": "t-main"},
    }
    mw = SideTaskGuardMiddleware(state)
    out = mw.block(ToolCallView(name="task", id="c1"))
    assert out is not None
    assert "side 会话中不可用 sub-agents" in out
    assert "/side close" in out


def test_side_task_guard_passes_outside_side_and_read_tools():
    state = {
        "thread_id": "t-main",
        SIDE_THREADS_KEY: {"t-side"},
        SIDE_PARENTS_KEY: {"t-side": "t-main"},
    }
    mw = SideTaskGuardMiddleware(state)
    # 非 side 会话 task/execute 均放行
    assert mw.block(ToolCallView(name="task", id="c1")) is None
    assert mw.block(ToolCallView(name="execute", id="c2")) is None
    # side 会话读/搜工具放行
    state["thread_id"] = "t-side"
    assert mw.block(ToolCallView(name="read_file", id="c3")) is None
    assert mw.block(ToolCallView(name="grep", id="c4")) is None


def test_side_task_guard_blocks_execute_in_side():
    state = {
        "thread_id": "t-side",
        SIDE_THREADS_KEY: {"t-side"},
        SIDE_PARENTS_KEY: {"t-side": "t-main"},
    }
    mw = SideTaskGuardMiddleware(state)
    out = mw.block(ToolCallView(name="execute", id="c1"))
    assert out is not None
    assert "execute 被禁用" in out
    assert "/side close" in out


def test_side_task_guard_releases_after_close(monkeypatch):
    state = {"thread_id": "t-main"}
    side_open(state, "t-side", "t-main")
    state["thread_id"] = "t-side"
    mw = SideTaskGuardMiddleware(state)
    assert mw.block(ToolCallView(name="task", id="c1")) is not None
    assert mw.block(ToolCallView(name="execute", id="c2")) is not None
    # close 即时解除（零 agent 重建，共享 state 引用）
    monkeypatch.setattr(
        commands, "delete_session",
        lambda a, target, current: (f"已删除会话 {target}", None),
    )
    commands.close_side(_SideAgent(_msgs()), "t-side", state)
    assert mw.block(ToolCallView(name="task", id="c1")) is None
    assert mw.block(ToolCallView(name="execute", id="c2")) is None

def test_side_thread_write_blocked_mainline_unaffected():
    """核心隔离断言：side 成员强制 plan（写工具拦），主线线程不受影响、全局 mode 键不动。"""
    from src.plan_mode import PlanModeMiddleware

    state = {"thread_id": "t-main", "mode": "act"}
    side_open(state, "t-side", "t-main")
    mw = PlanModeMiddleware(state)
    # side 线程：写工具被 Plan 拦截
    state["thread_id"] = "t-side"
    out = mw.block(ToolCallView(name="write_file", id="c1"))
    assert out is not None and "Plan" in out
    # 主线线程：不受 side 影响（全局 act）
    state["thread_id"] = "t-main"
    assert mw.block(ToolCallView(name="write_file", id="c1")) is None
    # 全局 mode 键全程未动
    assert state["mode"] == "act"
