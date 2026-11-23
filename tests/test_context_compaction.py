"""上下文压缩 keep-first（默认 0）单元测试。
覆盖默认（纯上游）与钉头行为、工厂 trigger/trim 语义。全内存 fake，零磁盘。
"""

import asyncio

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage
from langchain.agents.middleware.types import ModelRequest

from src.context_compaction import KeepFirstCompactionMiddleware, build_compaction_middleware


class _FakeModel:
    def __init__(self, profile=None):
        self.profile = profile
        self._llm_type = "openai-chat"
        self.calls = []
        self.acalls = []

    def with_retry(self):
        return self

    def invoke(self, prompt, config=None, **kwargs):
        self.calls.append(prompt)
        return SimpleNamespace(text="SUMMARY-%d" % len(self.calls))

    async def ainvoke(self, prompt, config=None, **kwargs):
        self.acalls.append(prompt)
        return SimpleNamespace(text="ASYM-%d" % len(self.acalls))


class _FakeBackend:
    def __init__(self):
        self.written = []
        self.downloaded = []

    def download_files(self, *args, **kwargs):
        self.downloaded.append((args, kwargs))
        return []

    def write(self, *args, **kwargs):
        self.written.append((args, kwargs))
        return SimpleNamespace(error=None)

    def edit(self, *args, **kwargs):
        return SimpleNamespace(error=None)

    async def adownload_files(self, *args, **kwargs):
        self.downloaded.append((args, kwargs))
        return []

    async def awrite(self, *args, **kwargs):
        self.written.append((args, kwargs))
        return SimpleNamespace(error=None)

    async def aedit(self, *args, **kwargs):
        return SimpleNamespace(error=None)


def _msgs():
    return [HumanMessage(content="HEAD-0"), HumanMessage(content="MID-1"), AIMessage(content="MID-2")]


# ---- 默认 keep_first=0：纯上游，全量进 LLM prompt，结果无 Pinned 段
def test_default_no_pinned():
    model = _FakeModel()
    mw = KeepFirstCompactionMiddleware(model, backend=_FakeBackend())
    out = mw._create_summary(_msgs())
    assert len(model.calls) == 1
    assert "HEAD-0" in model.calls[0]
    assert "MID-1" in model.calls[0]
    assert "MID-2" in model.calls[0]
    assert "Pinned conversation head" not in out


# ---- keep_first=1：开头逐字钉住，LLM 只处理 middle
def test_pinned_head():
    model = _FakeModel()
    mw = KeepFirstCompactionMiddleware(model, backend=_FakeBackend(), keep_first=1)
    out = mw._create_summary(_msgs())
    assert len(model.calls) == 1
    assert "Pinned conversation head" in out
    assert "HEAD-0" in out
    assert "MID-1" in model.calls[0]
    assert "MID-2" in model.calls[0]
    assert "HEAD-0" not in model.calls[0]


# ---- keep_first=1 且 middle 空：0 次 LLM + 占位 + 仍钉 head
def test_pinned_middle_empty():
    model = _FakeModel()
    mw = KeepFirstCompactionMiddleware(model, backend=_FakeBackend(), keep_first=1)
    out = mw._create_summary([HumanMessage(content="ONLY")])
    assert len(model.calls) == 0
    assert "ONLY" in out
    assert "No previous conversation history" in out
    assert "Pinned conversation head" in out


# ---- 链式传播：更早的 head 原文随 summary 继续逐字保留
def test_chained_propagation():
    model = _FakeModel()
    mw = KeepFirstCompactionMiddleware(model, backend=_FakeBackend(), keep_first=1)
    first = mw._create_summary([HumanMessage(content="HEAD-0"), AIMessage(content="MID-1")])
    assert "HEAD-0" in first
    prior = HumanMessage(content=first, additional_kwargs={"lc_source": "summarization"})
    second = mw._create_summary([prior, HumanMessage(content="MA"), AIMessage(content="MB")])
    assert "HEAD-0" in second


# ---- async 与 sync 行为一致
def test_async_matches_sync():
    model = _FakeModel()
    mw = KeepFirstCompactionMiddleware(model, backend=_FakeBackend(), keep_first=1)
    msgs = [HumanMessage(content="HEAD-0"), HumanMessage(content="MID-1")]
    out = asyncio.run(mw._acreate_summary(msgs))
    assert len(model.acalls) == 1
    assert "HEAD-0" in out
    assert "MID-1" in model.acalls[0]
    assert "HEAD-0" not in model.acalls[0]


# ---- 工厂：默认（profile=None）走 tokens 170000 / messages 6，keep_first=0
def test_factory_default():
    mw = build_compaction_middleware(_FakeModel(), _FakeBackend())
    assert mw.keep_first == 0
    assert mw._lc_helper.trigger == ("tokens", 170000)
    assert mw._lc_helper.keep == ("messages", 6)


# ---- 工厂：profile 带 int max_input_tokens → fraction 0.85/0.10
def test_factory_profile_fraction():
    model = _FakeModel(profile={"max_input_tokens": 131072})
    mw = build_compaction_middleware(model, _FakeBackend())
    assert mw._lc_helper.trigger == ("fraction", 0.85)
    assert mw._lc_helper.keep == ("fraction", 0.10)


# ---- 工厂：auto>0 → trigger=("tokens", N)
def test_factory_auto_tokens_trigger():
    mw = build_compaction_middleware(_FakeModel(), _FakeBackend(), auto_compaction=5)
    assert mw._lc_helper.trigger == ("tokens", 5)
    assert mw.keep_first == 0


# ---- 工厂：auto>0 未显式传 trim → 保留类默认 4000（修复透传漂移）
def test_factory_auto_trim_default_4000():
    mw = build_compaction_middleware(_FakeModel(), _FakeBackend(), auto_compaction=5)
    assert mw._lc_helper.trim_tokens_to_summarize == 4000


# ---- 工厂：auto>0 显式传 trim → 用传入值
def test_factory_auto_trim_explicit():
    mw = build_compaction_middleware(_FakeModel(), _FakeBackend(), auto_compaction=5, trim_tokens_to_summarize=123)
    assert mw._lc_helper.trim_tokens_to_summarize == 123

# ---- wrap_model_call 全路径：触发→钉头 summary→保留尾部→备份落盘→事件
def test_wrap_model_call_full_path():
    model = _FakeModel()
    backend = _FakeBackend()
    mw = KeepFirstCompactionMiddleware(
        model,
        backend=backend,
        trigger=("messages", 4),
        keep=("messages", 2),
        keep_first=1,
    )
    # middle（keep_first=1 之后的待裁段）须以 human 开头：上游 trim_messages
    # 用 start_on="human"，前导 ai 消息会被丢弃，故此处排布为 human 起头。
    msgs = [
        HumanMessage(content="HEAD-0"),
        HumanMessage(content="H1"),
        AIMessage(content="A2"),
        HumanMessage(content="H3"),
        AIMessage(content="A4"),
        HumanMessage(content="H5"),
    ]
    seen = []

    def handler(req):
        seen.append(req)
        return SimpleNamespace(model=model, messages=[])

    request = ModelRequest(model=model, messages=list(msgs), state={})
    resp = mw.wrap_model_call(request, handler)
    assert len(seen) == 1
    out_msgs = seen[0].messages
    assert len(out_msgs) == 3
    summary_msg, kept_a, kept_b = out_msgs
    assert summary_msg.additional_kwargs["lc_source"] == "summarization"
    assert "Pinned conversation head" in summary_msg.content
    assert "HEAD-0" in summary_msg.content
    assert kept_a.content == "A4" and kept_b.content == "H5"
    # 备份已落盘（write 被调用，路径含 conversation_history）
    assert any("conversation_history" in str(a) for a, _ in backend.written)
    # 事件携带 cutoff 与 summary message
    ev = resp.command.update["_summarization_event"]
    assert ev["cutoff_index"] == 4
    assert ev["summary_message"] is summary_msg
    assert "HEAD-0" not in model.calls[0]
    assert "H1" in model.calls[0]
