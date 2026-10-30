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


def test_subagent_specs_carry_sanitize_middleware():
    """400 自愈覆盖到子代理：researcher / knowledge_keeper / 自定义子代理
    会话内多轮回传历史同样会撞网关脏数据（"Expected 'id' to be a string."
    同族），子图独立、主代理 sanitize 管不到 → 子代理 middleware 必须含
    SanitizeHistoryMiddleware。"""
    from src.config_agents import build_config_subagents
    from src.sanitize_history import SanitizeHistoryMiddleware
    from src.subagents import build_knowledge_keeper, build_researcher

    for spec in (
        build_researcher(),
        build_researcher(deny_middleware=object()),
        build_knowledge_keeper(),
        build_knowledge_keeper(project_root=".", vault_path="./vault"),
    ):
        assert any(isinstance(mw, SanitizeHistoryMiddleware) for mw in spec["middleware"]), spec["name"]

    customs = build_config_subagents(
        {"my_agent": {"description": "d", "system_prompt": "p"}},
        default_deny_middleware=object(),
    )
    assert any(isinstance(mw, SanitizeHistoryMiddleware) for mw in customs[0]["middleware"])

    perms_agent = build_config_subagents(
        {"my_agent": {"description": "d", "system_prompt": "p", "permissions": {"execute": "deny"}}},
        default_deny_middleware=object(),
    )
    assert any(isinstance(mw, SanitizeHistoryMiddleware) for mw in perms_agent[0]["middleware"])
