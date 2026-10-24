from contextlib import contextmanager
"""commands.py 命令分发与会话管理测试。

Seam: commands.boundary_checkpoints / resolve_checkpoint_id / list_history /
list_sessions / dispatch_command。用 fake agent 模拟 get_state_history 返回的
checkpoint，不触网、不碰真 checkpoints.sqlite。
"""

from src import commands


def _make_fake_cp(conn):
    """为 FakeConn 创建带 cursor() 的 FakeCp（消除重复定义）。"""
    class _FakeCp:
        pass
    cp = _FakeCp()
    cp.conn = conn

    @contextmanager
    def _cursor(transaction=True):
        yield conn

    cp.cursor = _cursor
    return cp


class FakeState:
    """模拟 get_state_history 返回的 checkpoint 对象。"""

    def __init__(self, cid, source, step, messages=None, next_=()):
        self.config = {"configurable": {"checkpoint_id": cid}}
        self.metadata = {"source": source, "step": step}
        self.values = {"messages": messages or []}
        self.next = next_


def _human(text):
    return type("H", (), {"type": "human", "content": text})()


def _ai(text):
    return type("A", (), {"type": "ai", "content": text})()


class FakeAgent:
    def __init__(self, states):
        self._states = states  # 从旧到新

    def get_state_history(self, config=None):
        return iter(reversed(self._states))  # 模拟：真实 API 从新到旧


def test_boundary_checkpoints_filters_loop_and_reverses():
    states = [
        FakeState("cid-0000000-aaaa", "input", -1, [_human("第一个问题")]),
        FakeState("cid-0000000-bbbb", "loop", 0),
        FakeState("cid-0000000-cccc", "loop", 1),
        FakeState("cid-0000000-dddd", "input", 2, [_human("第二个问题")]),
        FakeState("cid-0000000-eeee", "fork", 3),
    ]
    agent = FakeAgent(states)
    out = commands.boundary_checkpoints(agent, "t")
    sources = [s.metadata["source"] for s in out]
    assert sources == ["input", "input", "fork"]  # loop 被过滤，顺序从旧到新
    assert out[0].config["configurable"]["checkpoint_id"] == "cid-0000000-aaaa"


def test_list_history_shows_boundaries_with_labels():
    states = [
        FakeState("cid-0000000-aaaa", "input", -1, [_human("调研国产大模型最新动态")]),
        FakeState("cid-0000000-bbbb", "loop", 0),
        FakeState("cid-0000000-cccc", "fork", 1),
    ]
    agent = FakeAgent(states)
    text = commands.list_history(agent, "t")
    assert "user: 调研国产大模型" in text
    assert "分叉点" in text
    assert "1." in text
    assert "/replay" in text
    assert "loop" not in text


def test_resolve_checkpoint_id_by_history_index():
    states = [
        FakeState("cid-0000000-aaaa", "input", -1, [_human("第一个问题")]),
        FakeState("cid-0000000-bbbb", "loop", 0),
        FakeState("cid-0000000-cccc", "input", 1, [_human("第二个问题")]),
    ]
    agent = FakeAgent(states)
    assert commands.resolve_checkpoint_id(agent, "t", "1") == "cid-0000000-aaaa"
    assert commands.resolve_checkpoint_id(agent, "t", "2") == "cid-0000000-cccc"
    assert commands.resolve_checkpoint_id(agent, "t", "9") is None


def test_dispatch_replay_by_index():
    states = [
        FakeState("cid-0000000-aaaa", "input", -1, [_human("q")]),
        FakeState("cid-0000000-bbbb", "input", 0, [_human("q2")]),
    ]
    agent = FakeAgent(states)
    text, new_thread, replay_cid = commands.dispatch_command(agent, "t", "/replay 1")
    assert text is None
    assert replay_cid == "cid-0000000-aaaa"
    assert new_thread is None


def test_list_history_empty():
    text = commands.list_history(FakeAgent([]), "t")
    assert "暂无历史" in text


def test_resolve_checkpoint_id_supports_short_prefix():
    full = "1f19870f-3fe3-6ce3-8037-b3c3667fa67b"
    states = [
        FakeState(full, "input", -1, [_human("q")]),
        FakeState("1f19870f-aaaa-6ce3-8037-b3c3667fa67b", "input", 0, [_human("q2")]),
    ]
    agent = FakeAgent(states)
    assert commands.resolve_checkpoint_id(agent, "t", full) == full
    assert commands.resolve_checkpoint_id(agent, "t", "1f19870f-3fe3") == full  # 短 id 前缀
    assert commands.resolve_checkpoint_id(agent, "t", "1f19870f") is None  # 歧义


def test_list_sessions_filters_sched_threads():
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            # SQL 已含 WHERE NOT LIKE 'sched-%'，实际只返回非 sched 线程
            return [("default",), ("session-abc",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

    class FakeAgent2:
        checkpointer = FakeCp()

    text = commands.list_sessions(FakeAgent2())
    assert "default" in text
    assert "session-abc" in text
    assert "1." in text
    assert "/copy-session" in text
    assert "sched-tech-daily" not in text
    assert "/delete-session" in text


def test_resolve_session_target_by_index():
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("default",), ("session-abc",), ("session-xyz",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

    class FakeAgent:
        checkpointer = FakeCp()

    assert commands.resolve_session_target(FakeAgent(), "2") == "session-abc"
    assert commands.resolve_session_target(FakeAgent(), "9") is None


def test_dispatch_copy_session_command():
    text, new_thread, replay = commands.dispatch_command(object(), "session-1", "/copy-session")
    assert "已复制会话 ID: session-1" in text
    assert new_thread is None


def test_resolve_thread_id_prefix():
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("default",), ("session-abc123",), ("session-xyz",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

    class FakeAgent:
        checkpointer = FakeCp()

    assert commands.resolve_thread_id(FakeAgent(), "session-abc123") == "session-abc123"
    assert commands.resolve_thread_id(FakeAgent(), "session-abc") == "session-abc123"
    assert commands.resolve_thread_id(FakeAgent(), "session-") is None  # 歧义


def test_delete_session_removes_thread(monkeypatch, tmp_path):
    deleted: list[str] = []

    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("session-old",), ("default",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

        def delete_thread(self, thread_id):
            deleted.append(thread_id)

    class FakeAgent:
        checkpointer = FakeCp()

    monkeypatch.setattr(commands, "project_root", lambda: tmp_path)

    import src.inbox_snapshots as inbox_snapshots
    import src.time_travel as tt

    monkeypatch.setattr(inbox_snapshots, "delete_writes_for_thread", lambda root, tid: 2)
    monkeypatch.setattr(tt, "delete_snapshots_for_thread", lambda root, tid: 1)

    text, new_thread = commands.delete_session(FakeAgent(), "session-old", "default")
    assert deleted == ["session-old"]
    assert "已删除会话 session-old" in text
    assert new_thread is None


def test_delete_session_current_switches_thread(monkeypatch, tmp_path):
    deleted: list[str] = []

    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("session-old",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

        def delete_thread(self, thread_id):
            deleted.append(thread_id)

    class FakeAgent:
        checkpointer = FakeCp()

    monkeypatch.setattr(commands, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        "src.inbox_snapshots.delete_writes_for_thread", lambda root, tid: 0
    )
    monkeypatch.setattr(
        "src.time_travel.delete_snapshots_for_thread", lambda root, tid: 0
    )

    text, new_thread = commands.delete_session(FakeAgent(), "session-old", "session-old")
    assert deleted == ["session-old"]
    assert new_thread and new_thread.startswith("session-")
    assert "已删除当前会话" in text


def test_delete_session_rejects_sched():
    class FakeCp:
        def delete_thread(self, thread_id):
            raise AssertionError("should not delete")

    class FakeAgent:
        checkpointer = FakeCp()

    text, new_thread = commands.delete_session(
        FakeAgent(), "sched-tech-daily", "default"
    )
    assert "不能删除" in text
    assert new_thread is None


def test_dispatch_delete_session_command(monkeypatch, tmp_path):
    monkeypatch.setattr(
        commands,
        "delete_session",
        lambda agent, target, current: (f"deleted {target}", None),
    )

    text, new_thread, replay = commands.dispatch_command(
        object(), "default", "/delete-session session-abc"
    )
    assert text == "deleted session-abc"
    assert new_thread is None
    assert replay is None

    text2, new_thread2, _ = commands.dispatch_command(object(), "default", "/delete-session")
    assert text2 == "deleted default"


def test_session_thread_ids_filters_sched_threads():
    """sched-* 线程被 SQL WHERE 过滤，不返回。"""
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            # SQL 已含 WHERE NOT LIKE 'sched-%'，实际只返回非 sched 线程
            return [("default",), ("session-abc",)]

    class FakeCp:
        conn = FakeConn()

        @contextmanager
        def cursor(self, transaction=True):
            yield self.conn

    class FakeAgent2:
        checkpointer = FakeCp()

    threads = commands.session_thread_ids(FakeAgent2())
    assert threads == ["default", "session-abc"]


def test_list_snapshots_formats_oldest_first(monkeypatch):
    import src.time_travel as tt

    monkeypatch.setattr(
        tt,
        "list_snapshots",
        lambda root: [
            ("cid-0000000-aaaa", "default", "abcdef1234567890", "2026-08-15 06:43:59"),
            ("cid-0000000-bbbb", "default", "1122334455667788", "2026-08-16 10:15:00"),
        ],
    )
    text = commands.list_snapshots()
    assert "文件快照" in text
    assert "2026-08-15" in text
    assert "abcdef12" in text  # 短 commit (前10)
    assert "cid-0000000-a" in text  # 短 cid
    assert "cid-0000000-a" in text.split("\n")[1]  # 第一条是旧的
    assert "cid-0000000-b" in text.split("\n")[2]  # 第二条是新的
    assert "/rollback" in text


class FakeDispatchAgent:
    def __init__(self):
        self.checkpointer = None

    def get_state_history(self, config=None):
        return iter([])


def test_dispatch_unknown_command():
    text, new_thread, replay_cid = commands.dispatch_command(FakeDispatchAgent(), "t", "/bogus")
    assert "未知命令" in text
    assert new_thread is None
    assert replay_cid is None


def test_dispatch_history_command():
    text, new_thread, replay_cid = commands.dispatch_command(FakeDispatchAgent(), "t", "/history")
    assert "暂无历史" in text
    assert new_thread is None
    assert replay_cid is None


def test_dispatch_sessions_command():
    text, new_thread, replay_cid = commands.dispatch_command(FakeDispatchAgent(), "t", "/sessions")
    assert new_thread is None
    assert replay_cid is None


def test_dispatch_reload_without_scheduler():
    text, new_thread, replay_cid = commands.dispatch_command(FakeDispatchAgent(), "t", "/reload-schedules")
    assert "调度器未启动" in text
    assert new_thread is None
    assert replay_cid is None


def test_current_permissions_omits_defaults():
    state = {"default": "ask", "tools": {"execute": "allow", "write_file": "ask"}}
    out = commands.current_permissions(state)
    assert out == {"execute": "allow"}  # write_file==ask 省略，default 无 *


def test_current_permissions_keeps_non_default():
    state = {"default": "allow", "tools": {"execute": "deny", "write_file": "allow"}}
    out = commands.current_permissions(state)
    assert out == {"*": "allow", "execute": "deny"}


def test_always_approve_rejects_non_gated_tool():
    assert commands.always_approve({"default": "ask", "tools": {}}, "read_file") is False


def test_always_approve_persists_gated_tool(monkeypatch, tmp_path):
    state = {"default": "ask", "tools": {"execute": "ask", "write_file": "ask"}}

    class Cfg:
        pass

    import src.commands as cmds
    import src.permissions as perms

    written = {}

    def fake_dump(permissions, json_path):
        written["permissions"] = permissions
        written["path"] = json_path

    def fake_apply(state, tool, action, value="*"):
        state["tools"][tool] = action

    monkeypatch.setattr(cmds, "project_root", lambda: tmp_path)
    monkeypatch.setattr(perms, "dump_permissions_json", fake_dump)
    monkeypatch.setattr(perms, "apply_permission_override", fake_apply)

    assert commands.always_approve(state, "execute") is True
    assert state["tools"]["execute"] == "allow"
    assert written["permissions"] == {"execute": "allow"}


def test_cli_help_and_tui_help_share_commands():
    assert "/exit" in commands.CLI_HELP
    assert "/exit" in commands.TUI_HELP
    assert "/delete-session" in commands.CLI_HELP
    assert "Ctrl+Insert" in commands.TUI_HELP
    assert "[y]本次放行" in commands.CLI_HELP
    assert "按钮" in commands.TUI_HELP
    assert "[y]本次放行" not in commands.TUI_HELP


def test_tool_invocation_from_action_execute():
    inv = commands.ToolInvocation.from_action({"name": "execute", "args": {"command": "ls -la"}})
    assert inv.name == "execute"
    assert inv.path == "ls -la"
    assert inv.args == {"command": "ls -la"}


def test_tool_invocation_from_action_write_file():
    inv = commands.ToolInvocation.from_action({"name": "write_file", "args": {"file_path": "/tmp/x.py"}})
    assert inv.name == "write_file"
    assert inv.path == "/tmp/x.py"


def test_content_to_text_skips_tool_call_blocks():
    blocks = [
        {"type": "tool_call", "id": "c1", "name": "task", "args": {"subagent_type": "researcher"}},
        {"type": "text", "text": "正在委派"},
    ]
    assert commands.content_to_text(blocks) == "正在委派"
    assert commands.content_to_text([{"type": "tool_call", "name": "task"}]) == ""


def test_render_ignores_tool_call_only_content():
    ai = type("A", (), {"type": "ai", "content": [{"type": "tool_call", "name": "task", "args": {}}]})()
    assert commands.render([ai]) == ""


class FakeReplayAgent:
    def __init__(self, states):
        self._states = states

    def get_state_history(self, config=None):
        return iter(reversed(self._states))


def test_prepare_replay_resolves_checkpoint():
    cid = "cid-0000000-aaaa"
    agent = FakeReplayAgent([FakeState(cid, "input", -1, [_human("q")])])
    err, full_id = commands.prepare_replay(agent, "t", cid[:13])
    assert err is None
    assert full_id == cid


def test_prepare_replay_unknown_checkpoint():
    err, full_id = commands.prepare_replay(FakeReplayAgent([]), "t", "missing-id")
    assert "重跑失败" in err
    assert full_id is None


def test_dispatch_replay_command():
    cid = "cid-0000000-aaaa"
    agent = FakeReplayAgent([FakeState(cid, "input", -1, [_human("q")])])
    text, new_thread, replay_cid = commands.dispatch_command(agent, "t", f"/replay {cid[:13]}")
    assert text is None
    assert replay_cid == cid
    assert new_thread is None


def test_dispatch_replay_unknown_checkpoint():
    agent = FakeReplayAgent([])
    text, new_thread, replay_cid = commands.dispatch_command(agent, "t", "/replay missing-id")
    assert "重跑失败" in text
    assert new_thread is None
    assert replay_cid is None


def test_completed_turn_checkpoint_returns_end_of_saved_turn():
    input_cid = "cid-input-aaaaaa"
    end_cid = "cid-end-bbbbbbbb"
    next_input = "cid-input-cccccc"
    states = [
        FakeState(input_cid, "input", -1, [_human("你好")], next_=("model",)),
        FakeState(end_cid, "loop", 1, [_human("你好"), _ai("saved-hello")], next_=()),
        FakeState(
            next_input,
            "input",
            2,
            [_human("你好"), _ai("saved-hello"), _human("下一问")],
            next_=("model",),
        ),
    ]
    end = commands.completed_turn_checkpoint(FakeReplayAgent(states), "t", input_cid)
    assert end is not None
    assert end.config["configurable"]["checkpoint_id"] == end_cid
    assert commands.render(end.values["messages"]) == "saved-hello"


def test_completed_turn_checkpoint_pending_input_returns_none():
    cid = "cid-input-aaaaaa"
    agent = FakeReplayAgent([FakeState(cid, "input", -1, [_human("你好")], next_=("model",))])
    assert commands.completed_turn_checkpoint(agent, "t", cid) is None


class FakeForkAgent:
    def __init__(self, target_state, new_thread="fork-session-1"):
        self._target = target_state
        self._new_thread = new_thread
        self.update_calls = []

    def get_state_history(self, config=None):
        return iter([self._target])

    def update_state(self, config, values, as_node):
        self.update_calls.append((config, values, as_node))
        return {"configurable": {"thread_id": self._new_thread, "checkpoint_id": "new-cp"}}


class FakeRollbackDispatchAgent:
    def __init__(self, states):
        self._states = states

    def get_state_history(self, config=None):
        return iter(reversed(self._states))


def test_dispatch_fork_returns_new_thread():
    cid = "cid-0000000-aaaa"
    target = FakeState(cid, "input", -1, [_human("q")], next_=("model",))
    agent = FakeForkAgent(target)
    text, new_thread, replay_cid = commands.dispatch_command(agent, "default", f"/fork {cid[:13]}")
    assert "分叉" in text
    assert new_thread == "fork-session-1"
    assert agent.update_calls


def test_dispatch_rollback_includes_inbox_listing(monkeypatch, tmp_path):
    cid = "cid-0000000-aaaa"
    vault = tmp_path / "vault"
    vault.mkdir()
    agent = FakeRollbackDispatchAgent([FakeState(cid, "input", -1)])

    import src.inbox_snapshots as inbox_snapshots
    import src.time_travel as tt

    monkeypatch.setattr(commands, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tt, "resolve_commit", lambda root, full_id: "abc1234567")
    monkeypatch.setattr(tt, "rollback_commit", lambda root, commit: None)
    monkeypatch.setattr(
        inbox_snapshots,
        "restore_inbox_for_rollback",
        lambda root, vp, ag, tid, full_id: [
            ("/vault/Inbox/note.md", "还原"),
            ("/vault/Inbox/new.md", "删除"),
        ],
    )

    text, new_thread, replay_cid = commands.dispatch_command(
        agent, "session-1", f"/rollback {cid[:13]}", vault_path=vault
    )
    assert "已回退项目文件" in text
    assert "Inbox/Reports 还原:" in text
    assert "/vault/Inbox/note.md" in text
    assert "删除 /vault/Inbox/new.md" in text
    assert "/replay" in text
    assert new_thread is None


def test_dispatch_rollback_reports_empty_inbox(monkeypatch, tmp_path):
    cid = "cid-0000000-bbbb"
    vault = tmp_path / "vault"
    vault.mkdir()
    agent = FakeRollbackDispatchAgent([FakeState(cid, "input", -1)])

    import src.inbox_snapshots as inbox_snapshots
    import src.time_travel as tt

    monkeypatch.setattr(commands, "project_root", lambda: tmp_path)
    monkeypatch.setattr(tt, "resolve_commit", lambda root, full_id: None)
    monkeypatch.setattr(
        inbox_snapshots,
        "restore_inbox_for_rollback",
        lambda *args, **kwargs: [],
    )

    text, _, replay_cid = commands.dispatch_command(
        agent, "session-1", f"/rollback {cid[:13]}", vault_path=vault
    )
    assert "未找到 checkpoint" in text or "跳过项目文件回退" in text
    assert "Inbox/Reports：该会话无需要还原的文件" in text


def test_channel_values_stuck_detects_pregel_tasks_and_branch():
    assert not commands.channel_values_stuck(None)
    assert not commands.channel_values_stuck({"messages": []})
    assert commands.channel_values_stuck({"__pregel_tasks": [{"id": "x"}]})
    assert commands.channel_values_stuck({"branch:to:model": None})


def test_repair_stuck_thread_rolls_back_to_last_good_checkpoint():
    class FakeTuple:
        def __init__(self, channel_values):
            self.checkpoint = {"channel_values": channel_values}

    class FakeCheckpointer:
        def __init__(self):
            self.by_cid = {
                "bad": {"__pregel_tasks": [{"id": "x"}], "branch:to:model": None},
                "good": {"messages": []},
            }
            self.updated = None

        def get_tuple(self, config):
            cid = config["configurable"].get("checkpoint_id")
            if cid is None:
                return FakeTuple(self.by_cid["bad"])
            return FakeTuple(self.by_cid[cid])

        def delete_thread(self, thread_id):
            self.deleted = thread_id

    class RepairAgent:
        def __init__(self):
            self.checkpointer = FakeCheckpointer()
            self._states = [
                FakeState("good", "input", -1),
                FakeState("bad", "loop", 1),
            ]

        def get_state_history(self, config=None):
            return iter(reversed(self._states))

        def update_state(self, config, values):
            self.checkpointer.updated = config

    agent = RepairAgent()
    assert commands.repair_stuck_thread(agent, "default") is True
    assert agent.checkpointer.updated == {
        "configurable": {
            "thread_id": "default",
            "checkpoint_id": "good",
            "checkpoint_ns": "",
        }
    }


def test_turn_needs_finalize_detects_stuck_and_pending_next(monkeypatch):
    class CleanState:
        def __init__(self):
            self.next = ()

    class PendingState:
        def __init__(self):
            self.next = ("model",)

    class CleanAgent:
        checkpointer = object()

        def get_state(self, config=None):
            return CleanState()

    class PendingAgent:
        checkpointer = object()

        def get_state(self, config=None):
            return PendingState()

    monkeypatch.setattr(commands, "checkpoint_config_stuck", lambda *a, **k: False)
    assert not commands.turn_needs_finalize(CleanAgent(), "t")
    assert commands.turn_needs_finalize(PendingAgent(), "t")
    monkeypatch.setattr(commands, "checkpoint_config_stuck", lambda *a, **k: True)
    assert commands.turn_needs_finalize(CleanAgent(), "t")


def test_finalize_turn_rolls_back_pending_interrupt():
    class FakeTuple:
        def __init__(self, channel_values):
            self.checkpoint = {"channel_values": channel_values}

    class FakeCheckpointer:
        def __init__(self):
            self.by_cid = {
                "pending": {"messages": []},
                "good": {"messages": []},
            }
            self.updated = None

        def get_tuple(self, config):
            cid = config["configurable"].get("checkpoint_id")
            if cid is None:
                return FakeTuple({"messages": []})
            return FakeTuple(self.by_cid[cid])

    class PendingState:
        def __init__(self, cid, *, next=()):
            self.config = {"configurable": {"checkpoint_id": cid}}
            self.next = next

    class FinalizeAgent:
        def __init__(self):
            self.checkpointer = FakeCheckpointer()
            self._history = [
                PendingState("good", next=()),
                PendingState("pending", next=("tools",)),
            ]

        def get_state(self, config=None):
            return PendingState("pending", next=("tools",))

        def get_state_history(self, config=None):
            return iter(reversed(self._history))

        def update_state(self, config, values):
            self.checkpointer.updated = config

    agent = FinalizeAgent()
    assert commands.turn_needs_finalize(agent, "default") is True
    assert commands.finalize_turn(agent, "default") is True
    assert agent.checkpointer.updated == {
        "configurable": {
            "thread_id": "default",
            "checkpoint_id": "good",
            "checkpoint_ns": "",
        }
    }


def test_format_agent_error_mentions_delete_session():
    class BadRequestError(Exception):
        pass

    err = BadRequestError("Error code: 400 - {'model': 'muse-spark'}")
    from src import streaming

    msg = streaming.format_agent_error(err)
    assert "/delete-session" in msg
    assert "-n" in msg


class _FakeCheckpointer:
    def __init__(self, *, stuck: bool = False, cp_count: int = 0, cp_max: int = 0):
        self.stuck = stuck
        self.cp_count = cp_count
        self.cp_max = cp_max

    def get_tuple(self, config):
        if not self.stuck:
            return None
        return type("T", (), {"checkpoint": {"channel_values": {"__pregel_tasks": [{}]}}})()


class _FakeConn:
    def __init__(self, count, max_size):
        self._count = count
        self._max = max_size

    def execute(self, sql, params=()):
        return self

    def fetchone(self):
        return (self._count, self._max)


class _FakeDoctorAgent:
    def __init__(self, *, stuck=False, messages=None, cp_count=0, cp_max=0):
        self.checkpointer = _FakeCheckpointer(stuck=stuck)
        self.checkpointer.conn = _FakeConn(cp_count, cp_max)
        self._messages = messages or []

    def get_state(self, config=None):
        return type("S", (), {"values": {"messages": self._messages}})()


def test_format_doctor_report_healthy(tmp_path, monkeypatch):
    from src.config import Config

    monkeypatch.setattr(commands, "resolve_env_file", lambda root: tmp_path / ".env")
    monkeypatch.setattr(commands, "resolve_jarvis_json", lambda root: tmp_path / "jarvis.json")
    (tmp_path / ".env").write_text("BASE_URL=http://x\nAPI_KEY=secret\nMODEL_ID=m\nTAVILY_KEY=t", encoding="utf-8")
    (tmp_path / "jarvis.json").write_text('{"obsidian_vault":"v","permissions":{"*":"ask"}}', encoding="utf-8")

    cfg = Config(
        project_root=tmp_path,
        base_url="http://x",
        api_key="secret-key",
        model_id="m",
        tavily_key="t",
        vault_path=(tmp_path / "v").resolve(),
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(),
        mcps={"servers": {}},
        permissions={"*": "ask"},
        hooks={},
        agents={},
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="embed",
        execution_max_steps=200,
        tui={"theme": "flexoki"},
    )
    from src.agent import _register_jarvis_harness

    _register_jarvis_harness("m")
    agent = _FakeDoctorAgent(messages=[_human("hi")], cp_count=3, cp_max=1200)
    text = commands.format_doctor_report(cfg, agent, "default", mcp_tool_count=0)
    assert "JARVIS 诊断" in text
    assert "会话状态:   正常" in text
    assert "m" in text
    assert "secr…" in text
    assert "permissions: *=ask" in text
    assert "消息条数:   1" in text
    assert "execute 已加载" in text
    assert "write_todos 已加载" in text
    assert "quick_search 已配置" in text
    assert "HarnessProfile: 已加载 (m)" in text
    assert "permission hooks: 0" in text
    assert "skills:" in text


def test_format_doctor_report_stuck(tmp_path, monkeypatch):
    from src.config import Config

    monkeypatch.setattr(commands, "resolve_env_file", lambda root: tmp_path / ".env")
    monkeypatch.setattr(commands, "resolve_jarvis_json", lambda root: tmp_path / "jarvis.json")

    cfg = Config(
        project_root=tmp_path,
        base_url="http://x",
        api_key="k",
        model_id="m",
        tavily_key="t",
        vault_path=tmp_path,
        memory_dir=tmp_path,
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path,
        skills=(),
        mcps={},
        permissions={},
        hooks={},
        agents={},
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="embed",
        execution_max_steps=200,
        tui={},
    )
    agent = _FakeDoctorAgent(stuck=True)
    text = commands.format_doctor_report(cfg, agent, "default")
    assert "⚠ 未完成" in text
    assert "/delete-session" in text


def test_dispatch_doctor(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.config.load_config",
        lambda: type("C", (), {
            "project_root": tmp_path,
            "base_url": "u",
            "api_key": "k",
            "model_id": "m",
            "tavily_key": "t",
            "vault_path": tmp_path,
            "memory_dir": tmp_path,
            "checkpoint_db": tmp_path / "cp.sqlite",
            "schedules_dir": tmp_path,
            "skills": (),
            "mcps": {},
            "permissions": {},
            "agents": {},
            "rag_ollama_base_url": "http://localhost:11434",
            "rag_embed_model": "e",
            "tui": {},
        })(),
    )
    monkeypatch.setattr("src.mcps.load_mcp_tools", lambda mcps: [])
    monkeypatch.setattr(commands, "format_doctor_report", lambda *a, **k: "doctor-ok")
    text, new_thread, replay = commands.dispatch_command(_FakeDoctorAgent(), "t1", "/doctor")
    assert text == "doctor-ok"
    assert new_thread is None
    assert replay is None

class _FakeSnapshot:
    def __init__(self, values):
        self.values = values


def _agent_with_thread(thread_id, messages):
    class FakeAgent:
        def get_state(self, config):
            assert config == {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            return _FakeSnapshot({"messages": messages})

    return FakeAgent()


class _Msg:
    def __init__(self, type_, content):
        self.type = type_
        self.content = content


def test_first_human_text_extracts_first_human():
    agent = _agent_with_thread(
        "t1",
        [_Msg("ai", "回复"), _Msg("human", "第一个问题"), _Msg("human", "第二个问题")],
    )
    assert commands.first_human_text(agent, "t1") == "第一个问题"


def test_first_human_text_truncates_and_flattens_newlines():
    long = "这是一个超过十八个字符的很长很长的中文问题内容继续继续"
    agent = _agent_with_thread("t1", [_Msg("human", f"  {long}\n第二行  ")])
    result = commands.first_human_text(agent, "t1")
    assert "\n" not in result
    assert len(result) <= 18
    assert result.startswith("这是")


def test_first_human_text_empty_falls_back_to_empty():
    agent = _agent_with_thread("t1", [_Msg("ai", "只有 ai 消息")])
    assert commands.first_human_text(agent, "t1") == ""


def test_first_human_text_state_error_returns_empty():
    class BoomAgent:
        def get_state(self, config):
            raise RuntimeError("boom")

    assert commands.first_human_text(BoomAgent(), "t1") == ""


def test_session_label_prefers_summary_falls_back_to_id():
    agent = _agent_with_thread("t1", [_Msg("human", "帮我写个 fizzbuzz 测试")])
    empty_agent = _agent_with_thread("t2", [])
    assert commands.session_label(agent, "t1") == "帮我写个 fizzbuzz 测试"[:18]
    assert commands.session_label(empty_agent, "t2") == "t2"


def test_list_sessions_shows_summary():
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("with-msg",), ("empty-thread",)]

    _cp_conn = FakeConn()

    def _cp_cursor(transaction=True):
        from contextlib import contextmanager
        @contextmanager
        def _inner(transaction=True):
            yield _cp_conn
        return _inner()

    class FakeAgent3:
        checkpointer = type("Cp", (), {"conn": _cp_conn, "cursor": _cp_cursor})()

        def get_state(self, config):
            tid = config["configurable"]["thread_id"]
            msgs = [] if tid == "empty-thread" else [_Msg("human", "帮我写个 fizzbuzz")]
            return _FakeSnapshot({"messages": msgs})

    text = commands.list_sessions(FakeAgent3())
    assert "帮我写个 fizzbuzz" in text
    assert "empty-thread" in text


def test_thread_config_literal_single_source():
    """⑥: checkpoint 配置字面量的唯一出处。"""
    assert commands.thread_config("t1") == {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}
    assert commands.thread_config("t1", "c9") == {
        "configurable": {"thread_id": "t1", "checkpoint_ns": "", "checkpoint_id": "c9"}
    }


def test_thread_history_text_extracts_all_messages():
    """#13: thread_history_text 返回全部消息（用户+AI）带角色标注。"""
    class _M:
        def __init__(self, type_, content):
            self.type = type_
            self.content = content

    class _Snap:
        def __init__(self, msgs):
            self.values = {"messages": msgs}

    agent = type("A", (), {
        "get_state_history": lambda self, config: iter([
            _Snap([_M("human", "你好"), _M("ai", "第一次回复"),
                   _M("human", "继续"), _M("ai", "第二次回复")]),
        ]),
    })()
    pairs = commands.thread_history_text(agent, "t1")
    assert pairs == [
        ("user", "你好"), ("ai", "第一次回复"),
        ("user", "继续"), ("ai", "第二次回复"),
    ]


def test_thread_history_text_empty():
    class _Snap:
        values = {"messages": []}
    agent = type("A", (), {
        "get_state_history": lambda self, config: iter([_Snap()]),
    })()
    assert commands.thread_history_text(agent, "t1") == []


def test_thread_history_text_max_messages():
    class _M:
        def __init__(self, t, c): self.type, self.content = t, c
    class _Snap:
        def __init__(self, msgs): self.values = {"messages": msgs}

    msgs = [_M("human", f"q{i}") if i % 2 == 0 else _M("ai", f"a{i}") for i in range(10)]
    agent = type("A", (), {
        "get_state_history": lambda self, config: iter([_Snap(msgs)]),
    })()
    pairs = commands.thread_history_text(agent, "t1", max_messages=4)
    assert len(pairs) == 4
    assert pairs[0] == ("user", "q6")


def test_thread_history_text_handles_list_content():
    """deepagents 消息 content 为 list[dict]（多模态块）。"""
    class _Snap:
        def __init__(self, msgs): self.values = {"messages": msgs}
    class _M:
        def __init__(self, t, c): self.type, self.content = t, c

    agent = type("A", (), {
        "get_state_history": lambda self, config: iter([
            _Snap([_M("ai", [{"type": "text", "text": "块格式回复"}])]),
        ]),
    })()
    pairs = commands.thread_history_text(agent, "t1")
    assert pairs == [("ai", "块格式回复")]


def test_thread_history_text_state_error():
    agent = type("A", (), {"get_state_history": lambda self, config: (_ for _ in ()).throw(RuntimeError("boom"))})()
    assert commands.thread_history_text(agent, "t1") == []


def test_last_ai_text_compat():
    """向后兼容：last_ai_text 取最后一条 AI 回复。"""
    class _M:
        def __init__(self, t, c): self.type, self.content = t, c
    class _Snap:
        def __init__(self, msgs): self.values = {"messages": msgs}

    agent = type("A", (), {
        "get_state_history": lambda self, config: iter([
            _Snap([_M("human", "q"), _M("ai", "最后回复")]),
        ]),
    })()
    assert commands.last_ai_text(agent, "t1") == "最后回复"


def _cfg_manual(tmp_path):
    """#09: 含 manual-only skill 的最小 Config（字段对齐 test_skill_discovery._cfg）。"""
    from src.config import Config

    sk = tmp_path / "skills" / "manual-skill"
    sk.mkdir(parents=True)
    (sk / "SKILL.md").write_text(
        "---\n"
        "name: manual-skill\n"
        "description: 手动专用 skill。\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        "# M\n"
        "步骤一：做点事\n",
        encoding="utf-8",
    )
    return Config(
        project_root=tmp_path,
        base_url="http://x",
        api_key="k",
        model_id="m",
        tavily_key="t",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(tmp_path / "skills",),
        mcps={},
        permissions={},
        hooks={},
        agents={},
        rag_ollama_base_url="http://localhost:11434",
        rag_embed_model="embed",
        execution_max_steps=200,
        tui={},
    )


def test_dispatch_skills_lists_manual_tag(tmp_path, monkeypatch):
    import src.config as config_mod

    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = _cfg_manual(tmp_path)
    monkeypatch.setattr(config_mod, "load_config", lambda: cfg)
    text, new_thread, replay = commands.dispatch_command(FakeAgent([]), "t", "/skills")
    assert new_thread is None and replay is None
    assert "manual-skill [manual]" in text
    assert "/use" in text


def test_expand_use_command_missing_skill_and_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path / "jh"))
    cfg = _cfg_manual(tmp_path)
    msg, err = commands.expand_use_command(cfg, "/use")
    assert msg is None and "用法" in err
    msg, err = commands.expand_use_command(cfg, "/use no-such-skill")
    assert msg is None and "未找到" in err
    msg, err = commands.expand_use_command(cfg, "/use manual-skill 请执行")
    assert err is None
    assert msg.startswith("[skill:manual-skill]")
    assert "步骤一：做点事" in msg
    assert "任务：请执行" in msg


# ---------------------------------------------------------------------------
# YOLO 模式（tui-ux12）：/yolo on | off 开关（线程级、仅本会话、幂等文案）
# ---------------------------------------------------------------------------

def test_dispatch_yolo_query_on_off_full_cycle():
    from src.permissions import build_permission_interrupts, yolo_active

    _io, state = build_permission_interrupts({})
    agent = FakeDispatchAgent()

    text, nt, rc = commands.dispatch_command(agent, "ty", "/yolo", permission_state=state)
    assert text == "YOLO 状态：本会话已关闭"
    assert nt is None and rc is None
    assert not yolo_active(state, "ty")  # 裸查询不改状态

    text, _, _ = commands.dispatch_command(agent, "ty", "/yolo on", permission_state=state)
    assert text == "YOLO 已开启：本会话所有动作免审批（vault 写保护与步数/熔断仍生效，/yolo off 关闭）"
    assert yolo_active(state, "ty")

    # 幂等：重复 on 回「已开启」短文案
    text, _, _ = commands.dispatch_command(agent, "ty", "/yolo on", permission_state=state)
    assert text == "YOLO 已开启（本会话免审批；vault 写保护、步数预算与熔断仍生效）"
    assert yolo_active(state, "ty")

    text, _, _ = commands.dispatch_command(agent, "ty", "/yolo off", permission_state=state)
    assert text == "YOLO 已关闭：恢复本会话原 permissions 规则"
    assert not yolo_active(state, "ty")

    # 幂等：重复 off 回「已关闭」短文案
    text, _, _ = commands.dispatch_command(agent, "ty", "/yolo off", permission_state=state)
    assert text == "YOLO 已关闭（本会话）"


def test_dispatch_yolo_bad_arg():
    from src.permissions import build_permission_interrupts

    _io, state = build_permission_interrupts({})
    text, nt, rc = commands.dispatch_command(FakeDispatchAgent(), "ty", "/yolo x", permission_state=state)
    assert text == "用法: /yolo on | /yolo off"
    assert nt is None and rc is None


def test_dispatch_yolo_without_permission_state_does_not_crash():
    text, nt, rc = commands.dispatch_command(FakeDispatchAgent(), "ty", "/yolo on")
    assert "不可用" in text
    assert nt is None and rc is None


def test_help_includes_yolo():
    assert "/yolo" in commands.CLI_HELP
    assert "/yolo" in commands.TUI_HELP
    assert "YOLO" in commands.CLI_HELP


# ---------------------------------------------------------------------------
# tui-ux13: build_submission 多行提交载荷（尾空白裁 + / 命令多行门禁）
# ---------------------------------------------------------------------------

def test_build_submission_single_line_unchanged():
    assert commands.build_submission("hello ") == ("hello", None)


def test_build_submission_strips_trailing_whitespace_and_newlines():
    assert commands.build_submission("第一行\na\n\n") == ("第一行\na", None)


def test_build_submission_empty_returns_none():
    assert commands.build_submission("") == (None, None)
    assert commands.build_submission("   \n  ") == (None, None)


def test_build_submission_slash_multiline_rejected():
    assert commands.build_submission("/history\nx") == (None, "/ 命令请放一行")
    assert commands.build_submission("  /history\nx") == (None, "/ 命令请放一行")


def test_build_submission_slash_single_line_allowed():
    assert commands.build_submission("/history") == ("/history", None)


def test_build_submission_virtual_prefix_multiline_allowed():
    vpm = ("/workspace/", "/vault/")
    assert commands.build_submission("/workspace/ls\n--detail", vpm) == ("/workspace/ls\n--detail", None)


# --- /compact ----------------------------------------------------------------

class FakeCompactModel:
    def __init__(self, content="这是摘要内容", fail=False):
        self.content = content
        self.fail = fail
        self.prompts = []

    def invoke(self, msgs):
        self.prompts.append([m.content for m in msgs])
        if self.fail:
            raise RuntimeError("boom")
        from langchain_core.messages import AIMessage

        return AIMessage(content=self.content)


class FakeCompactAgent:
    def __init__(self, messages, model=None):
        self.messages = messages
        self.model = model
        self._jarvis_model = model
        self.checkpointer = None
        self.state_updates = []

    def get_state(self, cfg, *a, **k):
        return type("Head", (), {"values": {"messages": self.messages}})()

    def update_state(self, cfg, values, as_node=None, **k):
        self.state_updates.append((cfg, values, as_node))
        return None


def _compact_msgs():
    from langchain_core.messages import AIMessage, HumanMessage

    return [
        HumanMessage(content="问题一"),
        AIMessage(content="回答一"),
        HumanMessage(content="问题二"),
        AIMessage(content="回答二"),
    ]


def test_compact_no_model():
    agent = FakeCompactAgent(_compact_msgs(), model=None)
    assert commands.compact(agent, "t") == "无法压缩上下文：模型不可用"
    assert agent.state_updates == []


def test_compact_too_few_messages():
    agent = FakeCompactAgent(_compact_msgs()[:3], model=FakeCompactModel())
    text = commands.compact(agent, "t")
    assert text.startswith("消息太少（3 条")
    assert agent.state_updates == []


def test_compact_success_rewrites_history():
    from langchain_core.messages import SystemMessage

    agent = FakeCompactAgent(_compact_msgs(), model=FakeCompactModel())
    text = commands.compact(agent, "t")
    assert text.startswith("已压缩上下文：原 4 条消息")
    assert len(agent.state_updates) == 1
    cfg, values, as_node = agent.state_updates[0]
    assert as_node == "model"
    assert len(values["messages"]) == 2
    from langgraph.graph.message import REMOVE_ALL_MESSAGES

    assert values["messages"][0].id == REMOVE_ALL_MESSAGES
    assert isinstance(values["messages"][1], SystemMessage)
    assert values["messages"][1].content == "[上下文压缩]\n这是摘要内容"


def test_compact_guide_appended_to_prompt():
    agent = FakeCompactAgent(_compact_msgs(), model=FakeCompactModel())
    commands.compact(agent, "t", guide="保留关键命令")
    prompt = agent.model.prompts[0][0]
    assert "用户提示" in prompt
    assert "保留关键命令" in prompt


def test_compact_empty_summary_keeps_history():
    agent = FakeCompactAgent(_compact_msgs(), model=FakeCompactModel(content=""))
    assert commands.compact(agent, "t") == "上下文压缩失败：模型未返回摘要，历史未改动"
    assert agent.state_updates == []


def test_compact_exception_keeps_history():
    agent = FakeCompactAgent(_compact_msgs(), model=FakeCompactModel(fail=True))
    text = commands.compact(agent, "t")
    assert "RuntimeError" in text and "boom" in text
    assert agent.state_updates == []


def test_dispatch_compact_no_model():
    agent = FakeCompactAgent(_compact_msgs(), model=None)
    out = commands.dispatch_command(agent, "t", "/compact")
    assert out == ("无法压缩上下文：模型不可用", None, None)


def test_dispatch_compact_with_guide():
    agent = FakeCompactAgent(_compact_msgs(), model=FakeCompactModel())
    out = commands.dispatch_command(agent, "t", "/compact 保留重要结论")
    text, new_thread, replay_cid = out
    assert text.startswith("已压缩")
    assert new_thread is None and replay_cid is None
    assert any("保留重要结论" in p[0] for p in agent.model.prompts)
