"""SystemHeadMiddleware（调用时 system 头合并）单测。

网关硬规则：wire 请求恰好一个 System 且位于 index 0。/side 边界
System 与 /compact 摘要 System 散在历史时，必须在模型调用时并入
请求级 system 头，且不改存储历史。纯内存 ModelRequest 假件，
无磁盘依赖（本机 tmp_path WinError 5 纪律）。
"""
import asyncio

from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.system_head import SystemHeadMiddleware


def _req(messages, system="主 agent prompt"):
    return ModelRequest(
        model=None,
        messages=list(messages),
        system_message=SystemMessage(content=system) if system else None,
    )


def _run(request):
    mw = SystemHeadMiddleware()
    captured = []
    mw.wrap_model_call(request, lambda r: captured.append(r) or "ok")
    assert captured, "handler not called"
    return captured[0]


def test_no_system_passes_through():
    req = _req([HumanMessage("你好", id="m1"), AIMessage("收到", id="a1")])
    out = _run(req)
    assert out is req  # 无 System 的零开销直通：原样返回
    assert out.system_message is not None
    assert "主 agent prompt" in out.system_message.content


def test_single_head_system_merged_when_request_system_present():
    boundary = SystemMessage(content="[side] 本会话是主线 t-main 的侧边会话", id="b1")
    msgs = [boundary, HumanMessage("问题", id="m1")]
    out = _run(_req(msgs))
    assert out.system_message is not None
    head = out.system_message.content
    assert "主 agent prompt" in head
    assert "side" in head
    assert head.index("主 agent prompt") < head.index("side")  # 请求级在前、历史按序在后
    assert [m.id for m in out.messages] == ["m1"]
    # 原历史引用不被改动（存储形式保持）
    assert isinstance(msgs[0], SystemMessage)


def test_multiple_interleaved_systems_merged_in_order():
    c1 = SystemMessage(content="[compact] 摘要 1", id="c1")
    c2 = SystemMessage(content="[injected] 注入 2", id="c2")
    msgs = [HumanMessage("h1", id="m1"), c1, AIMessage("a1", id="a1"), c2, HumanMessage("h2", id="m2")]
    out = _run(_req(msgs))
    head = out.system_message.content
    assert head.index("主 agent prompt") < head.index("[compact]") < head.index("[injected]")
    assert [m.id for m in out.messages] == ["m1", "a1", "m2"]
    assert not any(isinstance(m, SystemMessage) for m in out.messages)


def test_no_request_system_still_single_head():
    c1 = SystemMessage(content="仅有历史 System", id="c1")
    out = _run(_req([c1, HumanMessage("h", id="m1")], system=None))
    assert out.system_message is not None
    assert "仅有历史 System" in out.system_message.content
    assert [m.id for m in out.messages] == ["m1"]


def test_empty_system_content_dropped_cleanly():
    empty = SystemMessage(content="", id="e1")
    msgs = [empty, HumanMessage("h", id="m1")]
    out = _run(_req(msgs))
    head = out.system_message.content.strip()
    assert head == "主 agent prompt"  # 空 System 不留悬挂分隔符
    assert [m.id for m in out.messages] == ["m1"]


def test_async_path_same_merge():
    boundary = SystemMessage(content="[side] 边界", id="b1")
    req = _req([boundary, HumanMessage("h", id="m1")])
    captured = []

    async def _handler(r):
        captured.append(r)
        return "ok"

    asyncio.run(SystemHeadMiddleware().awrap_model_call(req, _handler))
    out = captured[0]
    assert "主 agent prompt" in out.system_message.content
    assert "边界" in out.system_message.content
    assert [m.id for m in out.messages] == ["m1"]
