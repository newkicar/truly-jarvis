"""commands.py 命令分发与会话管理测试。

Seam: commands.boundary_checkpoints / resolve_checkpoint_id / list_history /
list_sessions / dispatch_command。用 fake agent 模拟 get_state_history 返回的
checkpoint，不触网、不碰真 checkpoints.sqlite。
"""

from src import commands


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
            return [("default",), ("sched-tech-daily",), ("session-abc",)]

    class FakeCp:
        conn = FakeConn()

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
    class FakeConn:
        def execute(self, sql):
            return self

        def fetchall(self):
            return [("default",), ("sched-tech-daily",), ("session-abc",)]

    class FakeCp:
        conn = FakeConn()

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
        "configurable": {"thread_id": "default", "checkpoint_id": "good"}
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
        "configurable": {"thread_id": "default", "checkpoint_id": "good"}
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
    monkeypatch.setattr(commands, "resolve_javis_json", lambda root: tmp_path / "javis.json")
    (tmp_path / ".env").write_text("BASE_URL=http://x\nAPI_KEY=secret\nMODEL_ID=m\nTAVILY_KEY=t", encoding="utf-8")
    (tmp_path / "javis.json").write_text('{"obsidian_vault":"v","permissions":{"*":"ask"}}', encoding="utf-8")

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
    monkeypatch.setattr(commands, "resolve_javis_json", lambda root: tmp_path / "javis.json")

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
            assert config == {"configurable": {"thread_id": thread_id}}
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

    class FakeAgent3:
        checkpointer = type("Cp", (), {"conn": FakeConn()})()

        def get_state(self, config):
            tid = config["configurable"]["thread_id"]
            msgs = [] if tid == "empty-thread" else [_Msg("human", "帮我写个 fizzbuzz")]
            return _FakeSnapshot({"messages": msgs})

    text = commands.list_sessions(FakeAgent3())
    assert "帮我写个 fizzbuzz" in text
    assert "empty-thread" in text


def test_thread_config_literal_single_source():
    """⑥: checkpoint 配置字面量的唯一出处。"""
    assert commands.thread_config("t1") == {"configurable": {"thread_id": "t1"}}
    assert commands.thread_config("t1", "c9") == {
        "configurable": {"thread_id": "t1", "checkpoint_id": "c9"}
    }
