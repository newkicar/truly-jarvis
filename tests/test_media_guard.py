"""媒体守卫（src/media_guard.py）：文本-only 模型下二进制 ToolMessage 降级测试。

纯内存断言，无 tmp_path / tempfile（基 temp 目录 WinError 5 纪律）。
网关 400「Unsupported content part」防护：read_file 读到 .docx/.xlsx/.png 等
二进制时 deepagents 产出 base64 媒体 block，middleware 在模型调用前替换为
中文占位文本（含路径 + mime），整轮不再死亡。
"""
import asyncio

from langchain.agents.middleware import ModelRequest
from langchain.messages import HumanMessage, ToolMessage

from src.config_agents import build_config_subagents
from src.media_guard import MediaGuardMiddleware, scrub_unsupported_media_blocks
from src.subagents import build_knowledge_keeper, build_researcher


def _tool_with_media() -> ToolMessage:
    return ToolMessage(
        content=[
            {"type": "text", "text": "文件已读取"},
            {
                "type": "file",
                "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "data": "UEsDBB0=",
                "filename": "notes.docx",
            },
        ],
        name="read_file",
        tool_call_id="call_1",
        additional_kwargs={"read_file_path": "notes.docx"},
    )


def test_scrub_replaces_media_block_with_placeholder():
    out = scrub_unsupported_media_blocks([_tool_with_media()])
    assert out[0] is not out  # 新 list
    blocks = out[0].content
    assert blocks[0] == {"type": "text", "text": "文件已读取"}  # 文本块保留
    assert blocks[1]["type"] == "text"
    assert "notes.docx" in blocks[1]["text"]
    assert "wordprocessingml" in blocks[1]["text"]


def test_scrub_clean_list_returns_identity():
    msgs = [
        HumanMessage(content="hi"),
        ToolMessage(content="plain str", name="read_file", tool_call_id="c1"),
    ]
    assert scrub_unsupported_media_blocks(msgs) is msgs


def test_scrub_human_message_media_blocks_also_scrubbed():
    """当前实现对任何含媒体 block 的消息都降级（含 HumanMessage 图片粘贴块）。"""
    m = HumanMessage(content=[
        {"type": "image", "url": "data:image/png;base64,iVBOR"},
        {"type": "text", "text": "看图"},
    ])
    out = scrub_unsupported_media_blocks([m])
    assert out is not [m]
    assert out[0].content[0]["type"] == "text"


def test_wrap_model_call_scrubs_and_delegates():
    mg = MediaGuardMiddleware()
    req = ModelRequest(model=object(), messages=[_tool_with_media()])
    captured = {}

    def handler(r):
        captured["req"] = r
        return "OK"

    out = mg.wrap_model_call(req, handler)
    assert out == "OK"
    got = captured["req"]
    assert got is not req
    assert all(b.get("type") != "file" for b in got.messages[0].content)


def test_wrap_model_call_clean_passthrough():
    mg = MediaGuardMiddleware()
    req = ModelRequest(model=object(), messages=[HumanMessage(content="hi")])
    out = mg.wrap_model_call(req, lambda r: ("got", r))
    assert out[0] == "got"
    assert out[1] is req  # 无改动 → 原 request 透传


def test_awrap_model_call_awaits_handler():
    """回归：async 路径必须 await handler（旧实现 lambda 返回 coroutine 未 await）。"""
    mg = MediaGuardMiddleware()
    req = ModelRequest(model=object(), messages=[_tool_with_media()])

    async def handler(r):
        assert not any(b.get("type") == "file" for b in r.messages[0].content)
        return "async-ok"

    out = asyncio.run(mg.awrap_model_call(req, handler))
    assert out == "async-ok"


def test_subagent_wiring_researcher():
    mg = MediaGuardMiddleware()
    spec = build_researcher(media_guard=mg)
    assert mg in spec["middleware"]
    assert mg not in build_researcher()["middleware"]


def test_subagent_wiring_knowledge_keeper():
    mg = MediaGuardMiddleware()
    spec = build_knowledge_keeper(
        project_root="C:/proj", vault_path="C:/proj/vault", media_guard=mg
    )
    assert mg in spec["middleware"]
    assert mg not in build_knowledge_keeper()["middleware"]


def test_config_subagents_wiring():
    mg = MediaGuardMiddleware()
    agents = {"ops": {"description": "d", "system_prompt": "p"}}
    specs = build_config_subagents(
        agents, default_deny_middleware="DUMMY", media_guard=mg
    )
    assert specs and mg in specs[0]["middleware"]
    specs0 = build_config_subagents(agents, default_deny_middleware="DUMMY")
    assert mg not in specs0[0]["middleware"]
