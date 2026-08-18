"""Inbox 写入快照 middleware。"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware

from src import inbox_snapshots
from src.permissions import _tool_arg_value
from src.vault_guard import normalize_vault_path


class InboxSnapshotMiddleware(AgentMiddleware):
    """Inbox 写入前记录快照（供 /rollback 还原）。"""

    def __init__(self, project_root, vault_root):
        super().__init__()
        self.project_root = project_root
        self.vault_root = vault_root

    @property
    def name(self) -> str:
        return "inbox-snapshot"

    def _context(self, request) -> tuple[str, str, str, str]:
        tool_call = getattr(request, "tool_call", None) or {}
        tool = tool_call.get("name", "") if isinstance(tool_call, dict) else ""
        args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
        path = normalize_vault_path(_tool_arg_value(args, "file_path", "path"))
        runtime = getattr(request, "runtime", None)
        config = getattr(runtime, "config", None) or {}
        conf = config.get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = conf.get("thread_id", "")
        checkpoint_id = conf.get("checkpoint_id", "")
        return tool, path, thread_id, checkpoint_id

    def wrap_tool_call(self, request, handler):
        tool, path, thread_id, checkpoint_id = self._context(request)
        should_record = inbox_snapshots.is_inbox_write_tool(tool, path)
        pre_exists, pre_content = (
            inbox_snapshots.read_pre_state(self.vault_root, path) if should_record else (False, None)
        )
        result = handler(request)
        from langchain_core.messages import ToolMessage

        if isinstance(result, ToolMessage) and getattr(result, "status", None) == "error":
            return result
        if should_record and thread_id:
            inbox_snapshots.record_write(
                self.project_root,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                virtual_path=path,
                pre_exists=pre_exists,
                pre_content=pre_content,
            )
        return result

    async def awrap_tool_call(self, request, handler):
        tool, path, thread_id, checkpoint_id = self._context(request)
        should_record = inbox_snapshots.is_inbox_write_tool(tool, path)
        pre_exists, pre_content = (
            inbox_snapshots.read_pre_state(self.vault_root, path) if should_record else (False, None)
        )
        result = await handler(request)
        from langchain_core.messages import ToolMessage

        if isinstance(result, ToolMessage) and getattr(result, "status", None) == "error":
            return result
        if should_record and thread_id:
            inbox_snapshots.record_write(
                self.project_root,
                thread_id=thread_id,
                checkpoint_id=checkpoint_id,
                virtual_path=path,
                pre_exists=pre_exists,
                pre_content=pre_content,
            )
        return result
