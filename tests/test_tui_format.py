"""TUI 格式化纯函数测试。"""
from pathlib import Path

from src.commands import ToolInvocation
from src.tui_format import (
    AiStreamThrottler,
    ai_stream_renderable,
    format_file_diff,
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


def test_permission_preview_write_new_file(tmp_path):
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
    assert "新建文件" in text
    assert "Title" in text
    assert "body" in text


def test_permission_preview_edit_unified_diff(tmp_path):
    vault = tmp_path / "vault" / "Inbox"
    vault.mkdir(parents=True)
    f = vault / "note.md"
    f.write_text("line one\nline two\n", encoding="utf-8")
    inv = ToolInvocation.from_action(
        {
            "name": "edit_file",
            "args": {
                "file_path": "/vault/Inbox/note.md",
                "old_string": "line two",
                "new_string": "line TWO",
            },
        }
    )
    text = permission_preview(inv, vault_path=tmp_path / "vault", workspace_root=tmp_path)
    assert "---" in text
    assert "-line two" in text or "-line two\n" in text
    assert "+line TWO" in text


def test_format_file_diff_truncates_long_diff():
    before = "\n".join(f"old{i}" for i in range(50))
    after = "\n".join(f"new{i}" for i in range(50))
    text = format_file_diff(before, after, path="/vault/Inbox/x.md", max_lines=10)
    assert "已截断" in text


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
    assert "新建文件" in text
    assert "Title" in text


def test_permission_preview_reads_existing_file_as_diff(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    f = vault / "note.md"
    f.write_text("existing content", encoding="utf-8")
    inv = ToolInvocation.from_action(
        {
            "name": "edit_file",
            "args": {
                "file_path": "/vault/note.md",
                "old_string": "existing",
                "new_string": "updated",
            },
        }
    )
    text = permission_preview(inv, vault_path=vault, workspace_root=tmp_path)
    assert "---" in text
    assert "existing" in text
    assert "updated" in text
