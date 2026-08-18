"""Vault 写边界测试。"""
from src.vault_guard import (
    VaultWriteGuardMiddleware,
    is_inbox_path,
    is_vault_path,
    vault_write_blocked,
)


class _FakeRequest:
    def __init__(self, tool_call):
        self.tool_call = tool_call


def test_is_inbox_path():
    assert is_inbox_path("/vault/Inbox/note.md")
    assert is_inbox_path("/vault/Inbox")
    assert not is_inbox_path("/vault/Notes/foo.md")
    assert not is_inbox_path("/workspace/foo.md")


def test_vault_write_blocked_outside_inbox():
    assert vault_write_blocked("write_file", "/vault/Notes/foo.md")
    assert vault_write_blocked("edit_file", "/vault/x.md")
    assert vault_write_blocked("delete", "/vault/old.md")
    assert not vault_write_blocked("write_file", "/vault/Inbox/new.md")
    assert not vault_write_blocked("write_file", "/workspace/x.py")
    assert not vault_write_blocked("read_file", "/vault/Notes/x.md")


def test_guard_blocks_vault_outside_inbox():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Notes/foo.md"}, "id": "1"}
    )
    result = mw.wrap_tool_call(req, lambda r: "ok")
    assert result.status == "error"
    assert "Inbox" in result.content


def test_guard_allows_inbox():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Inbox/new-note.md"}, "id": "1"}
    )
    assert mw.wrap_tool_call(req, lambda r: "ok") == "ok"


def test_guard_allows_workspace():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/workspace/src/x.py"}, "id": "1"}
    )
    assert mw.wrap_tool_call(req, lambda r: "ok") == "ok"


def test_guard_blocks_delete_outside_inbox():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "delete", "args": {"path": "/vault/Notes/old.md"}, "id": "1"}
    )
    result = mw.wrap_tool_call(req, lambda r: "ok")
    assert result.status == "error"
