from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from src.tool_call import ToolCallView, tool_call_view


class GuardMiddleware(AgentMiddleware):

    def block(self, view: ToolCallView) -> str | None:
        raise NotImplementedError

    def _to_error(self, view: ToolCallView, message: str) -> ToolMessage:
        return ToolMessage(
            content=message,
            name=view.name,
            tool_call_id=view.id,
            status="error",
        )

    def wrap_tool_call(self, request, handler):
        view = tool_call_view(request)
        message = self.block(view)
        if message is not None:
            return self._to_error(view, message)
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        view = tool_call_view(request)
        message = self.block(view)
        if message is not None:
            return self._to_error(view, message)
        return await handler(request)


__all__ = ["GuardMiddleware"]
