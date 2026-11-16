"""调用时合并系统消息（网关 400 自愈，/side 与 /compact 同源根因）。

网关硬规则（实证 2026-11-16，本地代理 /chat/completions 探测）：
wire 请求必须**恰好一个 System 且位于 index 0**。但 checkpoint 历史里会
出现 SystemMessage（side 边界、/compact 摘要、注入提示等），请求级
system_message 又是主 agent 提示词 → 调用时双 System → 400
"System message must be at the beginning."

本中间件在 wrap_model_call（调用时）合并、**不写历史**：把
request.messages 中全部 SystemMessage 的文本按原顺序拼接到请求级
system_message 尾部，保证 wire 恰好一个 System 在 0 位。
checkpoint / undo / fork / GUI 转录显示均不受影响；无 System 历史的
常规线程走零开销直通。
"""
from __future__ import annotations

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import SystemMessage

__all__ = ["SystemHeadMiddleware"]


def _system_text(msg) -> str:
    """提取 SystemMessage 文本（text 优先，回落 content），去首尾空白。"""
    return str(getattr(msg, "text", None) or getattr(msg, "content", "") or "").strip()


class SystemHeadMiddleware(AgentMiddleware):
    """把散在历史里的 SystemMessage 合并进唯一 system 头（网关硬规则）。

    无状态、无副作用：直通路径（历史无 System）原样返回请求；
    合并路径复制消息列表（原历史引用不被改动）后 override 新请求。
    """

    @property
    def name(self) -> str:
        return "system-head"

    def _prepare(self, request):
        messages = list(getattr(request, "messages", None) or [])
        systems = [m for m in messages if isinstance(m, SystemMessage)]
        if not systems:
            return request
        rest = [m for m in messages if not isinstance(m, SystemMessage)]
        merged = _system_text(getattr(request, "system_message", None))
        for s in systems:
            text = _system_text(s)
            if text:
                merged = f"{merged}\n\n{text}" if merged else text
        return request.override(
            system_message=SystemMessage(content=merged),
            messages=rest,
        )

    def wrap_model_call(self, request, handler):
        return handler(self._prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._prepare(request))
