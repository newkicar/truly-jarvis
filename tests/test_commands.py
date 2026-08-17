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
    assert "cid-0000000-a" in text  # 短 id 可见，可复制用于 /replay
    assert "loop" not in text


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
    assert "sched-tech-daily" not in text


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
    text, new_thread = commands.dispatch_command(FakeDispatchAgent(), "t", "/bogus")
    assert "未知命令" in text
    assert new_thread is None


def test_dispatch_history_command():
    text, new_thread = commands.dispatch_command(FakeDispatchAgent(), "t", "/history")
    assert "暂无历史" in text
    assert new_thread is None


def test_dispatch_sessions_command():
    text, new_thread = commands.dispatch_command(FakeDispatchAgent(), "t", "/sessions")
    assert new_thread is None


def test_dispatch_reload_without_scheduler():
    text, new_thread = commands.dispatch_command(FakeDispatchAgent(), "t", "/reload-schedules")
    assert "调度器未启动" in text
    assert new_thread is None


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