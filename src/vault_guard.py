"""Vault 写边界：仅 Inbox 可写。"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware

from src.permissions import _tool_arg_value

VAULT_PREFIX = "/vault/"
INBOX_PREFIX = "/vault/Inbox/"
VAULT_WRITE_TOOLS = frozenset({"write_file", "edit_file", "delete"})


def normalize_vault_path(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


def is_vault_path(path: str) -> bool:
    norm = normalize_vault_path(path)
    return norm == "/vault" or norm.startswith(VAULT_PREFIX)


def is_inbox_path(path: str) -> bool:
    norm = normalize_vault_path(path)
    if not is_vault_path(norm):
        return False
    rest = norm[len("/vault") :].lstrip("/")
    return rest == "Inbox" or rest.startswith("Inbox/")


def vault_write_blocked(tool: str, path: str) -> bool:
    """Vault 外路径的 write/edit/delete 应被拦截。"""
    if tool not in VAULT_WRITE_TOOLS:
        return False
    if not is_vault_path(path):
        return False
    return not is_inbox_path(path)


def blocked_vault_write_message(tool: str, path: str, *, actor: str = "JARVIS") -> str:
    shown = path or "（未指定路径）"
    return (
        f"Permission denied: {actor} 只能写入 Vault 的 Inbox（{INBOX_PREFIX}），"
        f"不能对 {shown} 执行 {tool}。Vault 其它文件夹只读。"
    )


class VaultWriteGuardMiddleware(AgentMiddleware):
    """拦截对 Vault 非 Inbox 路径的 write_file / edit_file / delete。"""

    def __init__(self, *, actor: str = "JARVIS"):
        super().__init__()
        self.actor = actor

    @property
    def name(self) -> str:
        return "vault-write-guard"

    def _check(self, request) -> tuple[str, str] | None:
        tool_call = getattr(request, "tool_call", None) or {}
        if not isinstance(tool_call, dict):
            return None
        tool = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        path = normalize_vault_path(_tool_arg_value(args, "file_path", "path"))
        if vault_write_blocked(tool, path):
            return tool, path
        return None

    def _error_message(self, tool: str, path: str) -> str:
        return blocked_vault_write_message(tool, path, actor=self.actor)

    def wrap_tool_call(self, request, handler):
        blocked = self._check(request)
        if blocked:
            from langchain_core.messages import ToolMessage

            tool, path = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=self._error_message(tool, path),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._check(request)
        if blocked:
            from langchain_core.messages import ToolMessage

            tool, path = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=self._error_message(tool, path),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return await handler(request)


# 兼容旧名（knowledge_keeper 测试）
VaultInboxGuardMiddleware = VaultWriteGuardMiddleware
