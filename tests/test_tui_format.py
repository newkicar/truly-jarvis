"""TUI 格式化纯函数测试。"""
from pathlib import Path

from src.commands import ToolInvocation
from src.tui_format import (
    AiStreamThrottler,
    ai_stream_renderable,
    format_tool_call,
    permission_preview,
    truncate_lines,
)


def test_ai_stream_throttler_batches_deltas():
    t = AiStreamThrottler(interval=10.0)
    t.append("hel")
    assert t.due() is True
    t.mark_refreshed()
    t.append("lo")
    assert t.due() is False
    assert t.buffer == "hello"


def test_ai_stream_renderable_includes_header():
    group = ai_stream_renderable("# Title\n\nbody")
    assert group is not None
    assert len(group.renderables) == 2


def test_truncate_lines():
    text = "\n".join(f"line{i}" for i in range(15))
    out = truncate_lines(text, max_lines=10)
    assert "line9" in out
    assert "已截断" in out
    assert "line14" not in out


def test_format_tool_call_with_output():
    line = format_tool_call("grep", "pattern=x", output="a\nb\nc", indent=1)
    assert "grep" in line
    assert "a" in line
    assert "✓" in line


def test_permission_preview_execute():
    inv = ToolInvocation.from_action({"name": "execute", "args": {"command": "echo hi"}})
    assert "echo hi" in permission_preview(inv)


def test_permission_preview_write_content(tmp_path):
    inv = ToolInvocation.from_action(
        {
            "name": "write_file",
            "args": {"file_path": "/vault/Inbox/n.md", "content": "# Title\n\nbody"},
        }
    )
    text = permission_preview(
        inv,
        vault_path=tmp_path / "vault",
        workspace_root=tmp_path,
    )
    assert "Title" in text


def test_permission_preview_reads_existing_file(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    f = vault / "note.md"
    f.write_text("existing content", encoding="utf-8")
    inv = ToolInvocation.from_action(
        {"name": "edit_file", "args": {"file_path": "/vault/note.md", "old_string": "x"}}
    )
    text = permission_preview(inv, vault_path=vault, workspace_root=tmp_path)
    assert "existing content" in text
