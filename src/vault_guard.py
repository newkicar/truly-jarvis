"""Vault 写边界：仅 Inbox / Reports 等指定目录可写。

#10 路径放开后，write/edit/delete 可以携带真实盘符路径（如
D:/Obsidian/MyVault/Secrets/x.md）绕开 /vault/ 前缀——本 middleware 构造时
接收 vault 真实路径，_check 前先把落在 vault 目录内的真实路径映射回
/vault/... 虚拟形式再走同一套可写区判定（MAJOR 评审项修复）。
"""
from __future__ import annotations

from pathlib import Path

from langchain.agents.middleware.types import AgentMiddleware

from src.permissions import _tool_arg_value

VAULT_PREFIX = "/vault/"
INBOX_PREFIX = "/vault/Inbox/"
REPORTS_PREFIX = "/vault/Reports/"
# 允许 write/edit/delete 的 vault 顶层目录（不含子路径以外的任意文件夹）
VAULT_WRITABLE_TOP_DIRS = frozenset({"Inbox", "Reports"})
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


def is_reports_path(path: str) -> bool:
    norm = normalize_vault_path(path)
    if not is_vault_path(norm):
        return False
    rest = norm[len("/vault") :].lstrip("/")
    return rest == "Reports" or rest.startswith("Reports/")


def is_writable_vault_path(path: str) -> bool:
    """路径是否在允许 JARVIS 写入的 vault 目录内（Inbox、Reports 等）。"""
    norm = normalize_vault_path(path)
    if not is_vault_path(norm):
        return False
    rest = norm[len("/vault") :].lstrip("/")
    if not rest:
        return False
    top = rest.split("/")[0]
    return top in VAULT_WRITABLE_TOP_DIRS


def writable_vault_prefixes() -> tuple[str, ...]:
    return tuple(f"/vault/{name}/" for name in sorted(VAULT_WRITABLE_TOP_DIRS))


def vault_write_blocked(tool: str, path: str) -> bool:
    """Vault 非可写区路径的 write/edit/delete 应被拦截。"""
    if tool not in VAULT_WRITE_TOOLS:
        return False
    if not is_vault_path(path):
        return False
    return not is_writable_vault_path(path)


def blocked_vault_write_message(tool: str, path: str, *, actor: str = "JARVIS") -> str:
    shown = path or "（未指定路径）"
    allowed = "、".join(writable_vault_prefixes())
    return (
        f"Permission denied: {actor} 只能写入 Vault 的 {allowed}，"
        f"不能对 {shown} 执行 {tool}。Vault 其它文件夹只读。"
    )


class VaultWriteGuardMiddleware(AgentMiddleware):
    """拦截对 Vault 非可写区路径的 write_file / edit_file / delete。"""

    def __init__(self, *, actor: str = "JARVIS", vault_path=None):
        super().__init__()
        self.actor = actor
        self._vault_real = Path(vault_path).resolve() if vault_path else None

    def _virtualize(self, path: str) -> str:
        """落在 vault 目录内的真实盘符路径 → /vault/... 虚拟形式；其余原样返回。"""
        if self._vault_real is None or not path:
            return path
        p = Path(path)
        if not p.is_absolute():
            return path
        try:
            rel = p.resolve().relative_to(self._vault_real)
        except (ValueError, OSError):
            return path
        return "/vault/" + rel.as_posix()

    @property
    def name(self) -> str:
        return "vault-write-guard"

    def _check(self, request) -> tuple[str, str] | None:
        tool_call = getattr(request, "tool_call", None) or {}
        if not isinstance(tool_call, dict):
            return None
        tool = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        raw = _tool_arg_value(args, "file_path", "path")
        # 先尝试把真实路径映射回 /vault/...，再统一走虚拟路径判定
        virtualized = normalize_vault_path(self._virtualize(raw))
        path = normalize_vault_path(raw)
        for candidate in (virtualized, path):
            if vault_write_blocked(tool, candidate):
                return tool, candidate
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
