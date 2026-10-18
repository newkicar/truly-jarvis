"""历史清洗中间件（400 自愈：历史中畸形工具调用导致网关拒收）。

Bug 背景（历史中两类 400 触发源，都需成对清洗）：
1. **invalid_tool_calls**（HITL 中断轮 / 流式参数 JSON 被截断）：
   - 流式聚合失败时，langchain_openai 把解析失败的工具调用存进
     ``AIMessage.invalid_tool_calls``（保留原始参数字符串）；
   - 下一轮请求时 ``_lc_invalid_tool_call_to_openai_tool_call`` 把原始串直接塞进
     OpenAI ``arguments``（合法 tool_calls 走 json.dumps 保证合法；invalid 原样透传），
     网关严格校验 → 400 "arguments must be valid JSON"；
   - 同时 PatchToolCallsMiddleware 会为 invalid_tool_calls 补合成 ToolMessage，
     只删一边会制造「孤儿 tool message」的另一种 400，必须成对清除。
2. **空 tool_call / 孤儿结果**（流式聚合产出脏数据，实际事故）：
   - ``AIMessage.tool_calls`` 里混入 ``name=""``+``id=""`` 的空工具调用（在*合法*
     列表里，不在 invalid_tool_calls，旧实现看不见）；
   - ToolNode 对空名调用执行出错，产出 ``tool_call_id=""`` 的 error ToolMessage
     （孤儿）；下一轮网关（Rust 严格 serde）拒收整条请求 → 400 "missing field
     tool_call_id"。``tool_call_id`` 为 None 或悬空引用同样触发 400。

处置：``before_model``（每次模型调用前都会跑，resume 路径同样覆盖）检测含
invalid_tool_calls 或空调用的 AIMessage，重建之（保留 id/content，只留合法调用）；
预计算全历史合法调用 id 集合，移除 ``tool_call_id`` 为空/None 或不在其中
（悬空）的 ToolMessage（合成结果 / 孤儿 / 挂空悬全覆盖），用
REMOVE_ALL_MESSAGES 整表重写 messages 通道——清洗结果随 checkpoint 持久化，
历史一次自愈后不再复发。无脏数据返回 None，零开销。

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


def _bad_call(tc: Any) -> bool:
    """脏调用：非 dict，或 id/name 为空（网关序列化后拒收）。"""
    if not isinstance(tc, dict):
        return True
    return not tc.get("id") or not tc.get("name")


def _valid_call_ids(messages):
    """全历史 AI 消息中*合法* tool_call 的 id 集合（id、name 均非空）。"""
    ids = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls:
                if isinstance(tc, dict) and tc.get("id") and tc.get("name"):
                    ids.add(tc["id"])
    return ids


def _rebuild_ai(msg, keep_calls):
    """重建 AIMessage：保留 id/content/response_metadata，丢弃脏调用。

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
        tool_calls=list(keep_calls),
        invalid_tool_calls=[],
    )


def sanitize_messages(messages):
    """清洗消息历史；无需清洗时返回 None（零开销）。

    - 含 ``invalid_tool_calls`` 或空调用的 AIMessage 重建（保留 id/content/合法
      tool_calls，清空 invalid_tool_calls）；
    - ``tool_call_id`` 为空/None 或不在全历史合法调用 id 集合中的 ToolMessage
      移除（合成结果 / 孤儿 / 挂空悬全覆盖）；
    - 其余消息原样保留原顺序与 id。
    """
    valid_ids = _valid_call_ids(messages)

    kept = []
    changed = False
    for msg in messages:
        if isinstance(msg, AIMessage):
            dirty = bool(msg.invalid_tool_calls) or any(_bad_call(tc) for tc in msg.tool_calls)
            if dirty:
                kept.append(_rebuild_ai(msg, [tc for tc in msg.tool_calls if not _bad_call(tc)]))
                changed = True
            else:
                kept.append(msg)
        elif isinstance(msg, ToolMessage):
            if not msg.tool_call_id or msg.tool_call_id not in valid_ids:
                changed = True
            else:
                kept.append(msg)
        else:
            kept.append(msg)

    if not changed:
        return None
    return kept


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