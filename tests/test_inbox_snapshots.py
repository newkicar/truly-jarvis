"""Inbox 快照与回退测试。"""
from pathlib import Path

from src import inbox_snapshots


class _State:
    def __init__(self, checkpoint_id: str):
        self.config = {"configurable": {"checkpoint_id": checkpoint_id}}
        self.metadata = {}


class FakeRollbackAgent:
    def __init__(self, checkpoint_ids: list[str]):
        self._ids = checkpoint_ids  # newest first

    def get_state_history(self, config=None):
        for cid in self._ids:
            yield _State(cid)


def test_record_and_list_writes(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    inbox_snapshots.record_write(
        root,
        thread_id="t1",
        checkpoint_id="c-before",
        virtual_path="/vault/Inbox/a.md",
        pre_exists=False,
        pre_content=None,
    )
    rows = inbox_snapshots.list_writes(root, "t1")
    assert len(rows) == 1
    assert rows[0]["virtual_path"] == "/vault/Inbox/a.md"
    assert rows[0]["pre_exists"] is False


def test_restore_deletes_new_file(tmp_path):
    proj = tmp_path / "proj"
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "new.md"
    note.write_text("agent wrote this", encoding="utf-8")

    inbox_snapshots.record_write(
        proj,
        thread_id="session-1",
        checkpoint_id="c2",
        virtual_path="/vault/Inbox/new.md",
        pre_exists=False,
        pre_content=None,
    )
    agent = FakeRollbackAgent(["c3", "c2", "c1"])
    actions = inbox_snapshots.restore_inbox_for_rollback(
        proj, vault, agent, "session-1", "c1"
    )
    assert actions == [("/vault/Inbox/new.md", "删除")]
    assert not note.exists()


def test_restore_reverts_edit(tmp_path):
    proj = tmp_path / "proj"
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "edit.md"
    note.write_text("after edit", encoding="utf-8")

    inbox_snapshots.record_write(
        proj,
        thread_id="session-1",
        checkpoint_id="c2",
        virtual_path="/vault/Inbox/edit.md",
        pre_exists=True,
        pre_content="before edit",
    )
    agent = FakeRollbackAgent(["c2", "c1"])
    actions = inbox_snapshots.restore_inbox_for_rollback(
        proj, vault, agent, "session-1", "c1"
    )
    assert note.read_text(encoding="utf-8") == "before edit"
    assert any(a[1] == "还原" for a in actions)


def test_sched_thread_not_restored_on_session_rollback(tmp_path):
    proj = tmp_path / "proj"
    vault = tmp_path / "vault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)
    sched_note = inbox / "tech-daily.md"
    sched_note.write_text("from scheduler", encoding="utf-8")

    inbox_snapshots.record_write(
        proj,
        thread_id="sched-tech-daily",
        checkpoint_id="sched-run",
        virtual_path="/vault/Inbox/tech-daily.md",
        pre_exists=False,
        pre_content=None,
    )
    agent = FakeRollbackAgent(["c2", "c1"])
    actions = inbox_snapshots.restore_inbox_for_rollback(
        proj, vault, agent, "session-1", "c1"
    )
    assert actions == []
    assert sched_note.read_text(encoding="utf-8") == "from scheduler"
