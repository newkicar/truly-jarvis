"""knowledge_keeper vault 写入约束测试。"""
from src.vault_guard import VaultWriteGuardMiddleware

# 兼容旧测试 import
VaultInboxGuardMiddleware = VaultWriteGuardMiddleware


class _FakeRequest:
    def __init__(self, tool_call):
        self.tool_call = tool_call


def test_vault_inbox_guard_blocks_outside_inbox():
    mw = VaultInboxGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Notes/foo.md"}, "id": "1"}
    )
    result = mw.wrap_tool_call(req, lambda r: "ok")
    assert result.status == "error"
    assert "Inbox" in result.content


def test_vault_inbox_guard_allows_inbox():
    mw = VaultInboxGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Inbox/new-note.md"}, "id": "1"}
    )
    assert mw.wrap_tool_call(req, lambda r: "ok") == "ok"
