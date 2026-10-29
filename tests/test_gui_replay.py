"""工单 06 — 记录重建 thread_record：tool_call_id 配对 / 错误态 / 多模态 content。"""
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.gui.replay import thread_record


def _agent(messages):
    class _St:
        values = {"messages": messages}

    class _Agent:
        def get_state(self, cfg):
            return _St()

    return _Agent()


def test_user_ai_tool_pairing_by_call_id():
    ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "execute", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"},
            {"name": "write_file", "args": {"file_path": "a.txt", "content": "x"}, "id": "c2"},
        ],
    )
    msgs = [
        HumanMessage(content="看下文件"),
        ai,
        ToolMessage(content="[Command succeeded] 1 item", tool_call_id="c1", name="execute"),
        ToolMessage(content="wrote a.txt", tool_call_id="c2", name="write_file"),
        AIMessage(content="完成了"),
    ]
    recs = thread_record(_agent(msgs), "t1")
    kinds = [r.kind for r in recs]
    assert kinds == ["user", "tool", "tool", "ai"]
    tools = [r.tool for r in recs if r.kind == "tool"]
    assert tools[0].name == "execute" and "ls" in tools[0].args_text and not tools[0].error
    assert tools[0].output.startswith("[Command succeeded]")
    assert tools[1].name == "write_file"
    assert [r.text for r in recs if r.kind == "ai"] == ["完成了"]


def test_error_tool_marked():
    ai = AIMessage(
        content="",
        tool_calls=[{"name": "execute", "args": {"command": "nope"}, "id": "c9"}],
    )
    msgs = [
        ai,
        ToolMessage(
            content="[Command failed with exit code 1]",
            tool_call_id="c9",
            status="error",
            name="execute",
        ),
    ]
    recs = thread_record(_agent(msgs), "t2")
    tool = next(r for r in recs if r.kind == "tool")
    assert tool.tool.error is True
    assert "exit code 1" in tool.tool.output


def test_multimodal_content_blocks_flattened():
    h = HumanMessage(content=[{"type": "text", "text": "看这个"}, {"type": "image_url", "image_url": {"url": "data:..."}}])
    a = AIMessage(content=[{"type": "text", "text": "收到图片"}])
    recs = thread_record(_agent([h, a]), "t3")
    assert [r.text for r in recs if r.kind == "user"] == ["看这个"]  # 只取 text 块
    assert [r.text for r in recs if r.kind == "ai"] == ["收到图片"]


def test_missing_tool_message_keeps_call_line():
    ai = AIMessage(content="", tool_calls=[{"name": "grep", "args": {"pattern": "x"}, "id": "g1"}])
    recs = thread_record(_agent([ai]), "t4")  # 无对应 ToolMessage（中断轮）
    tool = next(r for r in recs if r.kind == "tool")
    assert tool.tool.name == "grep" and tool.tool.output == ""
