"""Vault 写边界测试。"""
from src.vault_guard import (
    VaultWriteGuardMiddleware,
    is_inbox_path,
    is_reports_path,
    is_vault_path,
    is_writable_vault_path,
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


def test_is_reports_path():
    assert is_reports_path("/vault/Reports/daily.md")
    assert is_reports_path("/vault/Reports")
    assert not is_reports_path("/vault/Inbox/x.md")


def test_is_writable_vault_path():
    assert is_writable_vault_path("/vault/Inbox/note.md")
    assert is_writable_vault_path("/vault/Reports/2026-08-18.md")
    assert not is_writable_vault_path("/vault/Notes/foo.md")


def test_vault_write_blocked_outside_inbox():
    assert vault_write_blocked("write_file", "/vault/Notes/foo.md")
    assert vault_write_blocked("edit_file", "/vault/x.md")
    assert vault_write_blocked("delete", "/vault/old.md")
    assert not vault_write_blocked("write_file", "/vault/Inbox/new.md")
    assert not vault_write_blocked("write_file", "/vault/Reports/daily.md")
    assert not vault_write_blocked("write_file", "/workspace/x.py")
    assert not vault_write_blocked("read_file", "/vault/Notes/x.md")


def test_guard_allows_reports():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Reports/tech-daily.md"}, "id": "1"}
    )
    assert mw.wrap_tool_call(req, lambda r: "ok") == "ok"


def test_guard_blocks_vault_outside_inbox():
    mw = VaultWriteGuardMiddleware()
    req = _FakeRequest(
        {"name": "write_file", "args": {"file_path": "/vault/Notes/foo.md"}, "id": "1"}
    )
    result = mw.wrap_tool_call(req, lambda r: "ok")
    assert result.status == "error"
    assert "Inbox" in result.content or "Reports" in result.content


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


def test_real_drive_path_to_protected_zone_blocked(tmp_path):
    """#10 后真实盘符路径也必须受 vault 写边界约束（MAJOR 评审项）。"""
    from types import SimpleNamespace

    from src.vault_guard import VaultWriteGuardMiddleware

    vault = tmp_path / "MyVault"
    secret = vault / "Archive"
    secret.mkdir(parents=True)
    inbox = vault / "Inbox"
    inbox.mkdir()

    mw = VaultWriteGuardMiddleware(vault_path=vault)
    req = SimpleNamespace(tool_call={
        "name": "write_file",
        "id": "c1",
        "args": {"file_path": str(secret / "x.md"), "content": "v"},
    })
    res = mw.wrap_tool_call(req, lambda r: "ran")
    assert getattr(res, "status", "") == "error"
    assert "Inbox" in str(res.content)


def test_real_drive_path_inbox_allowed(tmp_path):
    from types import SimpleNamespace

    from src.vault_guard import VaultWriteGuardMiddleware

    vault = tmp_path / "MyVault"
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True)

    mw = VaultWriteGuardMiddleware(vault_path=vault)
    marker: list = []
    req = SimpleNamespace(tool_call={
        "name": "write_file",
        "id": "c1",
        "args": {"file_path": str(inbox / "note.md"), "content": "v"},
    })
    assert mw.wrap_tool_call(req, lambda r: marker.append(1)) is None or True
    assert marker, "Inbox 内真实路径应放行"


def test_non_vault_real_path_unaffected(tmp_path):
    from types import SimpleNamespace

    from src.vault_guard import VaultWriteGuardMiddleware

    outside = tmp_path / "Other"
    outside.mkdir()
    mw = VaultWriteGuardMiddleware(vault_path=tmp_path / "MyVault")
    marker: list = []
    req = SimpleNamespace(tool_call={
        "name": "write_file",
        "id": "c1",
        "args": {"file_path": str(outside / "a.txt"), "content": "v"},
    })
    mw.wrap_tool_call(req, lambda r: marker.append(1))
    assert marker, "vault 之外的普通路径不受此守卫管辖"
