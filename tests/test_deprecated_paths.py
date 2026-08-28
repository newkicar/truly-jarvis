"""deprecated_paths 中间件测试。"""
from src.deprecated_paths import (
    DeprecatedPathMiddleware,
    deprecated_path_message,
    references_deprecated_path,
)
from src.tool_call import tool_call_view


class _Req:
    def __init__(self, name: str, args: dict):
        self.tool_call = {"name": name, "args": args, "id": "tc1"}


def test_references_deprecated_path():
    assert references_deprecated_path("/workspace/skills/system-context/scripts")
    assert references_deprecated_path("python read_context.py")
    assert not references_deprecated_path("/workspace/readme.md")


def test_blocks_ls_on_system_context():
    mw = DeprecatedPathMiddleware()
    req = _Req("ls", {"path": "/workspace/skills/system-context/scripts"})
    view = tool_call_view(req)
    message = mw.block(view)
    assert message is not None
    assert "system-context" in message


def test_blocks_execute_read_context_script():
    mw = DeprecatedPathMiddleware()
    req = _Req("execute", {"command": "python skills/system-context/scripts/read_context.py"})
    view = tool_call_view(req)
    message = mw.block(view)
    assert message is not None


def test_wrap_returns_error_tool_message():
    mw = DeprecatedPathMiddleware()
    req = _Req("glob", {"pattern": "**/system-context/**", "path": "/workspace/skills"})
    msg = mw.wrap_tool_call(req, handler=lambda r: None)
    assert msg.status == "error"
    assert "已废弃" in msg.content
    assert "Get-Date" in msg.content


def test_message_mentions_prompt_header():
    text = deprecated_path_message("ls", "/workspace/skills/system-context")
    assert "今天是" in text
