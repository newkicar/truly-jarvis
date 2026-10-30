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
   - ``id`` 不是字符串（int/None 型）同样被网关拒收："Expected 'id' to be a
     string."——``additional_kwargs["tool_calls"]``（流式中断残留，``.tool_calls``
     为空时被 langchain_openai 原样透传）里的脏 id 也归此类；
   - ToolNode 对空名调用执行出错，产出 ``tool_call_id=""`` 的 error ToolMessage
     （孤儿）；下一轮网关（Rust 严格 serde）拒收整条请求 → 400 "missing field
     tool_call_id"。``tool_call_id`` 为 None 或悬空引用同样触发 400。

3. **content 块列表里的网关不兼容 part**（本网关流式响应实测）：
   - 网关把 Responses-API 风格块（``{"type":"tool_call",...}``、thinking 等）
     放进 ``AIMessage.content``；下一轮 langchain_openai 原样回传 → 400
     "Unsupported chat content part type: 'tool_call'."（vLLM）/ 同族 "Expected
     'id' to be a string."（Rust 代理）；
    - 工具调用语义由 ``.tool_calls`` 字段承载，content 里的 tool_call 块纯冗余
      → 丢弃；text/多模态/thinking 块保留；
    - 保留块里的 ``id`` 同样受网关严格 serde 校验："thinking"/"refusal" 块的
      ``id`` 为 int/None 型会被同族网关拒收（"Expected 'id' to be a string."
      与该 400 同族）→ 剥离非字符串 id 键（防御性，合法字符串 id 不动）。

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
    """脏调用：非 dict，或 id/name 不是非空字符串（网关 serde 严格校验拒收）。

    ``id`` 必须是字符串：网关报 "Expected 'id' to be a string."（Rust serde 严格
    类型）——历史里混入 int/None 型 id 时整条请求 400。
    """
    if not isinstance(tc, dict):
        return True
    if not isinstance(tc.get("id"), str) or not tc["id"]:
        return True
    if not isinstance(tc.get("name"), str) or not tc["name"]:
        return True
    return False


def _bad_raw_call(tc: Any) -> bool:
    """``additional_kwargs["tool_calls"]`` 里的原始 OpenAI 调用是否脏。

    langchain_openai 的 ``_convert_message_to_dict`` 在 ``.tool_calls`` 为空时
    把 ``additional_kwargs["tool_calls"]`` **原样透传**（只裁剪键名，不做类型
    校验）——流式中断残留的 ``id: None`` / int 型 id 在这里躲过 ``_bad_call``，
    下一轮请求被网关拒收（"Expected 'id' to be a string."）。
    """
    if not isinstance(tc, dict):
        return True
    if not isinstance(tc.get("id"), str) or not tc["id"]:
        return True
    fn = tc.get("function")
    if not isinstance(fn, dict):
        return True
    return not isinstance(fn.get("name"), str) or not fn["name"]


def _raw_calls_dirty(msg: AIMessage) -> bool:
    raw = msg.additional_kwargs.get("tool_calls")
    if raw is None:
        return False
    if not isinstance(raw, list):
        return True
    return any(_bad_raw_call(tc) for tc in raw)


# 网关 chat-completions 请求 content 可接受的块类型（vLLM 实测支持列表；
# 该网关流式响应会用 Responses-API 风格块——tool_call/thinking 混在 content 里，
# 原样回传即 400："Unsupported chat content part type: 'tool_call'"（vLLM）/
# "Expected 'id' to be a string."（Rust 代理同类校验））。
_KEEP_CONTENT_TYPES = (
    "text", "input_text", "output_text",
    "image", "image_url", "input_image", "image_pil", "image_embeds",
    "audio_url", "input_audio", "audio_embeds",
    "video_url", "video_embeds",
    "thinking", "refusal", "prompt_embeds",
)


def _normalize_content(msg: AIMessage) -> tuple[Any, bool]:
    """归一化 AIMessage.content：丢弃网关不接受的 content part（tool_call/未知类型）。

    工具调用语义已由 ``.tool_calls`` 字段承载（网关按 tool_calls 校验），
    content 里的 tool_call 块纯冗余且致 400；text/多模态/thinking 块保留。
    另：保留块若带非字符串 ``id``（thinking/refusal 的 id=None/int，本网关流式
    响应常见）→ 剥离该键。Rust 代理对 content part 的 ``id`` 做严格 serde 校验，
    非字符串 id 原样回传即 400 "Expected 'id' to be a string."（旧 go 网关实证 200
    的假设在 Rust 代理上不再成立；thinking id 无工具回传语义，剥离无副作用）。
    返回 (新 content, 是否变化)。
    """
    c = msg.content
    if not isinstance(c, list):
        return c, False
    kept = []
    changed = False
    for b in c:
        if isinstance(b, str):
            kept.append(b)
            continue
        if not (isinstance(b, dict) and b.get("type") in _KEEP_CONTENT_TYPES):
            changed = True
            continue
        if "id" in b and not (isinstance(b.get("id"), str) and b["id"]):
            nb = dict(b)
            nb.pop("id", None)
            kept.append(nb)
            changed = True
        else:
            kept.append(b)
    if not changed:
        return c, False
    return (kept if kept else ""), True


def _valid_call_ids(messages):
    """全历史 AI 消息中*合法* tool_call 的 id 集合（id、name 均为非空字符串）。"""
    ids = set()
    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in msg.tool_calls:
                if not _bad_call(tc):
                    ids.add(tc["id"])
    return ids


def _rebuild_ai(msg, keep_calls, content=None):
    """重建 AIMessage：保留 id/response_metadata，丢弃脏调用。

    同时清掉 additional_kwargs 里可能残留的原始 tool_calls 列表，防御脏数据
    经其他路径再次混入 OpenAI 请求。content 非 None 时以归一化后的块列表替换
    （content part 清洗，与工具调用清洗同一次重建完成）。
    """
    extra = dict(msg.additional_kwargs)
    extra.pop("tool_calls", None)
    return AIMessage(
        content=(msg.content if content is None else content),
        additional_kwargs=extra,
        response_metadata=dict(msg.response_metadata),
        id=msg.id,
        tool_calls=list(keep_calls),
        invalid_tool_calls=[],
    )


def sanitize_messages(messages):
    """清洗消息历史；无需清洗时返回 None（零开销）。

    - 含 ``invalid_tool_calls`` 或空调用的 AIMessage 重建（保留 id/合法
      tool_calls，清空 invalid_tool_calls）；
    - AIMessage.content 块列表含网关不接受的 part（tool_call/未知类型）→
      归一化丢弃（text/多模态/thinking 保留），工具语义由 tool_calls 字段承载；
    - ``tool_call_id`` 为空/None 或不在全历史合法调用 id 集合中的 ToolMessage
      移除（合成结果 / 孤儿 / 挂空悬全覆盖）；
    - 其余消息原样保留原顺序与 id。
    """
    valid_ids = _valid_call_ids(messages)

    kept = []
    changed = False
    for msg in messages:
        if isinstance(msg, AIMessage):
            new_content, content_changed = _normalize_content(msg)
            dirty = (
                bool(msg.invalid_tool_calls)
                or any(_bad_call(tc) for tc in msg.tool_calls)
                or _raw_calls_dirty(msg)
                or content_changed
            )
            if dirty:
                kept.append(
                    _rebuild_ai(
                        msg,
                        [tc for tc in msg.tool_calls if not _bad_call(tc)],
                        content=(new_content if content_changed else None),
                    )
                )
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