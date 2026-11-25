"""上下文压缩（keep-first）：deepagents 原生 SummarizationMiddleware 的"钉住开头"子类。

deepagents 的压缩 = 触发阈值达到后，把旧消息交给 LLM 生成 summary，summary 替换旧消息，
被裁历史外置到 backend 的 conversation_history/{session_id}.md。

上游行为的一个已知缺陷：summary 里不包含对话开头的原文——开头的任务描述/约定如果落在
被裁区间里，就只剩 LLM 转述，逐字保真度丢失。本模块的子类在 summary 生成时把开头
keep_first 条消息（默认 0 即不钉；keep_first>0 才逐字钉开头 N 条）**逐字**（XML 序列化）钉进 summary 文本，中间段仍走上游
LLM 总结（trim + retry + 内部调用 metadata 全部保留），不经 LLM 的只有头钉部分。

链式传播：第二次压缩时，上一条 summary（HumanMessage，lc_source=summarization）本身成为
新的 head 候选，其中钉住的更早原文随 head 再次逐字传播——首条原文在整个压缩链中不丢。

行为开关：
- keep_first=0 或待裁列表为空 → 完全走上游 _create_summary，行为与原生等价（默认）；
- 中间段为空 → 上游对空列表返回 "No previous conversation history."（不调 LLM），
  与上游语义一致。

风险记录：本模块覆写的钩子（_create_summary/_acreate_summary）与上游私有 _lc_helper
委托绑定，deepagents 升级若改委托结构，需同步调整（单测 pin 住当前行为）。
"""

from __future__ import annotations

from typing import Any

from deepagents.middleware.summarization import (
    DEEPAGENTS_DEFAULT_SUMMARY_PROMPT,
    SummarizationMiddleware,
    compute_summarization_defaults,
)
from langchain_core.messages import AnyMessage, get_buffer_string

# 上游对空列表/trim 后为空的占位文案（与 langchain LC 侧行为一致，直接复用文案）
_EMPTY_HISTORY_PLACEHOLDER = "No previous conversation history."


class KeepFirstCompactionMiddleware(SummarizationMiddleware):
    """压缩时钉住开头 keep_first 条消息（逐字进 summary，不经 LLM）。

    触发、切点、外置备份、事件模型全部继承 deepagents 原生实现，本类只覆写
    summary 生成钩子（sync/async 两条 wrap_model_call 路径）。
    """

    def __init__(
        self,
        model: Any,
        *,
        backend: Any,
        keep_first: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, backend=backend, **kwargs)
        try:
            keep_first = int(keep_first)
        except (TypeError, ValueError):
            keep_first = 0
        self.keep_first = max(0, keep_first)

    # ---------------------------------------------------------------- 钩子

    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """钉头版 summary 生成（sync wrap_model_call 路径）。"""
        messages = list(messages_to_summarize)
        if self.keep_first == 0 or not messages:
            return super()._create_summary(messages)
        head = messages[: self.keep_first]
        middle = messages[self.keep_first :]
        # 中间段走上游：trim / retry / internal_call metadata / 空列表占位全保留
        middle_text = super()._create_summary(middle) if middle else _EMPTY_HISTORY_PLACEHOLDER
        return self._compose_pinned_summary(head, middle_text)

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """钉头版 summary 生成（async wrap_model_call 路径，与 offload 并发）。"""
        messages = list(messages_to_summarize)
        if self.keep_first == 0 or not messages:
            return await super()._acreate_summary(messages)
        head = messages[: self.keep_first]
        middle = messages[self.keep_first :]
        if middle:
            middle_text = await super()._acreate_summary(middle)
        else:
            middle_text = _EMPTY_HISTORY_PLACEHOLDER
        return self._compose_pinned_summary(head, middle_text)

    # ------------------------------------------------------------ 内部工具

    def _compose_pinned_summary(self, head: list[AnyMessage], middle_text: str) -> str:
        """拼接最终 summary：head 逐字 XML + 中间段 LLM 文本。"""
        head_xml = get_buffer_string(head, format="xml")
        return (
            "## Pinned conversation head (verbatim, do not re-summarize)\n"
            f"{head_xml}\n\n"
            "## LLM summary of remaining messages\n"
            f"{middle_text}"
        )


def build_compaction_middleware(
    model: Any,
    backend: Any,
    *,
    keep_first: int = 0,
    auto_compaction: int = 0,
    summary_prompt: str = DEEPAGENTS_DEFAULT_SUMMARY_PROMPT,
    trim_tokens_to_summarize: int | None = None,
    token_counter: Any | None = None,
) -> KeepFirstCompactionMiddleware:
    """构造 keep-first 压缩中间件（create_summarization_middleware 的钉头版）。

    - auto_compaction > 0：trigger 固定为 ("tokens", auto_compaction)，其余走上游默认；
    - 否则：compute_summarization_defaults(model) 全量透传（profile 有
      max_input_tokens 时 fraction 0.85/0.10，否则 tokens 170000 / messages 6 兜底），
      复刻 deepagents 原生 create_summarization_middleware 行为。
    """
    from langchain_core.messages.utils import count_tokens_approximately

    if token_counter is None:
        token_counter = count_tokens_approximately
    if auto_compaction > 0:
        kwargs: dict[str, Any] = dict(
            backend=backend,
            trigger=("tokens", int(auto_compaction)),
            keep_first=keep_first,
            summary_prompt=summary_prompt,
            token_counter=token_counter,
        )
        if trim_tokens_to_summarize is not None:
            kwargs["trim_tokens_to_summarize"] = trim_tokens_to_summarize
        return KeepFirstCompactionMiddleware(model, **kwargs)
    defaults = compute_summarization_defaults(model)
    return KeepFirstCompactionMiddleware(
        model,
        backend=backend,
        trigger=defaults["trigger"],
        keep=defaults["keep"],
        truncate_args_settings=defaults["truncate_args_settings"],
        keep_first=keep_first,
        summary_prompt=summary_prompt,
        trim_tokens_to_summarize=trim_tokens_to_summarize,
        token_counter=token_counter,
    )
