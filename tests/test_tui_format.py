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


def test_format_tool_call_markup_safe_with_unsafe_args():
    """工具行经 log.write → Rich markup 渲染：args/output 含 [ ' = 字符（pandas 式命令）
    直接嵌进 [dim]...[/dim] markup 串 → MarkupError 崩流式渲染。
    修复：动态片段 escape()，既有 [dim] 意图保留，渲染后原文不丢。"""
    from rich.console import Console

    unsafe = "cells=[" + "str(c) + '=' + str(ws.max_column)" + " for c in ws.columns]"
    args = "{'command': " + repr(unsafe) + "}"
    out = format_tool_call("execute", args, output="ok " + unsafe, indent=1)
    console = Console(record=True, width=200)
    console.print(out)  # 修复前：MarkupError
    plain = console.export_text()
    assert unsafe in plain, f"渲染后丢失原文: {plain!r}"


from src.tui_format import (
    REASONING_DISPLAY_CAP_LINES,
    TOOL_DETAIL_ARG_CAP,
    TOOL_DETAIL_OUT_CAP_LINES,
    reasoning_block_markup,
    tool_detail_block,
    tool_detail_worth_expanding,
)


# ---------------- tui-ux19: 工具详情展开 / 思考块 纯函数 ----------------

def test_tool_detail_worth_expanding_truth_table():
    """error / 非空输出 / 长参数 → True；普通短调用无输出 → False。"""
    assert tool_detail_worth_expanding("execute", "ls", error=True) is True
    assert tool_detail_worth_expanding("read_file", "path=x", output="abc") is True
    assert tool_detail_worth_expanding("grep", "q") is False
    long_args = "q" * 81
    assert tool_detail_worth_expanding("grep", long_args) is True
    assert tool_detail_worth_expanding("grep", "q" * 80) is False
    # 空白输出不算有输出 → 回落到参数长度判断
    assert tool_detail_worth_expanding("grep", "q", output="   ") is False


def test_format_tool_call_detail_marker():
    line = format_tool_call("execute", "ls", detail=True)
    assert "＋ 详情（点击展开/收起）" in line
    plain = format_tool_call("execute", "ls")
    assert "＋ 详情" not in plain


def test_tool_detail_block_markers_and_caps():
    block = tool_detail_block("read_file", "path=x")
    assert "参数: path=x" in block
    assert "＋ 收起（点击收起）" in block
    # 参数超 cap 截断 + 总字数尾注
    big = "a" * (TOOL_DETAIL_ARG_CAP + 50)
    block2 = tool_detail_block("grep", big)
    assert "截断，共 %d 字符）" % len(big) in block2
    assert "a" * (TOOL_DETAIL_ARG_CAP + 50) not in block2
    # 输出超行数截断
    out = "\n".join(f"l{i}" for i in range(TOOL_DETAIL_OUT_CAP_LINES + 20))
    block3 = tool_detail_block("execute", "ls", output=out)
    assert f"l{TOOL_DETAIL_OUT_CAP_LINES - 1}" in block3
    assert f"l{TOOL_DETAIL_OUT_CAP_LINES + 19}" not in block3


def test_reasoning_block_markup_cap_and_truncation_note():
    short = reasoning_block_markup("line1\nline2")
    assert "💭 思考" in short
    assert "line1" in short and "line2" in short
    lines = [f"t{i}" for i in range(REASONING_DISPLAY_CAP_LINES + 5)]
    capped = reasoning_block_markup("\n".join(lines))
    assert f"t{REASONING_DISPLAY_CAP_LINES + 4}" not in capped
    assert f"共 {REASONING_DISPLAY_CAP_LINES + 5} 行，已截断" in capped
    # 空文本只有标题
    assert reasoning_block_markup("") == "[dim italic]💭 思考[/dim italic]"
    assert reasoning_block_markup(None) == "[dim italic]💭 思考[/dim italic]"
