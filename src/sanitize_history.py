"""历史清洗中间件（400 自愈：历史中畸形工具调用参数导致网关拒收）。

Bug 背景（HITL 中断轮 / 流式参数 JSON 被截断 → 下一轮 400）：
- 流式聚合失败时，langchain_openai 把解析失败的工具调用存进
  ``AIMessage.invalid_tool_calls``（保留原始参数字符串）；
- 下一轮请求时 ``_lc_invalid_tool_call_to_openai_tool_call`` 把原始串直接塞进
  OpenAI ``arguments``（合法 tool_calls 走 json.dumps 保证合法；invalid 原样透传），
  网关严格校验 → 400 "arguments must be valid JSON"；
- 同时 PatchToolCallsMiddleware 会为 invalid_tool_calls 补合成 ToolMessage，
  只删一边会制造「孤儿 tool message」的另一种 400，必须成对清除。

处置：``before_model``（每次模型调用前都会跑，resume 路径同样覆盖）检测含
``invalid_tool_calls`` 的 AIMessage，剥掉坏调用并移除引用它们 id 的 ToolMessage
（合成或真实），用 REMOVE_ALL_MESSAGES 整表重写 messages 通道——清洗结果随
checkpoint 持久化，历史一次自愈后不再复发。无脏数据返回 None，零开销。

本中间件为自定义中间件，拼在 core（PatchToolCalls 等）之后执行，运行时会看到
合成 ToolMessage 已就位，成对删除后历史恒满足「每个 tool_call_id 必须有对应
前置 assistant 工具调用」约束。
"""
from __future__ import annotations

from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, AnyMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime


def _invalid_call_ids(messages):
    """收集历史中所有 invalid_tool_calls 的 id（含 None）。"""
    ids = set()
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.invalid_tool_calls:
            for bad in msg.invalid_tool_calls:
                ids.add(bad.get("id"))
    return ids


def _rebuild_without_invalid(msg):
    """重建 AIMessage：保留 id/content/合法 tool_calls，丢弃 invalid_tool_calls。

    同时清掉 additional_kwargs 里可能残留的原始 tool_calls 列表，防御脏数据
    经其他路径再次混入 OpenAI 请求。
    """
    extra = dict(msg.additional_kwargs)
    extra.pop("tool_calls", None)
    return AIMessage(
        content=msg.content,
        additional_kwargs=extra,
        response_metadata=dict(msg.response_metadata),
        id=msg.id,
        tool_calls=list(msg.tool_calls),
        invalid_tool_calls=[],
    )


def sanitize_messages(messages):
    """清洗消息历史；无需清洗时返回 None。

    - 含 ``invalid_tool_calls`` 的 AIMessage 重建（保留 id/content/合法 tool_calls）；
    - 引用这些坏调用 id 的 ToolMessage 移除（含 PatchToolCalls 合成的结果）；
    - 其余消息原样保留原顺序与 id。
    """
    bad_ids = _invalid_call_ids(messages)
    if not bad_ids:
        return None

    sanitized = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.invalid_tool_calls:
            sanitized.append(_rebuild_without_invalid(msg))
        elif isinstance(msg, ToolMessage) and msg.tool_call_id in bad_ids:
            continue
        else:
            sanitized.append(msg)
    return sanitized


class SanitizeHistoryMiddleware(AgentMiddleware):
    """模型调用前清除历史中的畸形工具调用及其工具结果引用（400 自愈）。"""

    @property
    def name(self):
        return "sanitize-history"

    def _run(self, state, runtime):
        messages = (
            state.get("messages", [])
            if isinstance(state, dict)
            else getattr(state, "messages", [])
        )
        sanitized = sanitize_messages(messages)
        if sanitized is None:
            return None
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *sanitized]}

    def before_model(self, state, runtime):
        return self._run(state, runtime)

    async def abefore_model(self, state, runtime):
        return self._run(state, runtime)
