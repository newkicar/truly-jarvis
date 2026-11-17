"""slash 命令补全测试。"""
from src.slash_completion import SLASH_COMMANDS, filter_commands, slash_query


def test_slash_query_line_start():
    assert slash_query("/his") == (0, "his")
    assert slash_query("/") == (0, "")


def test_slash_query_any_position_after_space():
    """tui-ux21: "space + /" anywhere on any line opens the command list."""
    assert slash_query("hello /x") == (6, "x")
    text = "第一行\n第二 /comp"
    assert slash_query(text) == (text.index("/"), "comp")
    # cursor mid-query: only text up to the cursor participates
    assert slash_query("hello /his more", 10) == (6, "his")


def test_slash_query_glued_slash_never_triggers():
    """non-whitespace before "/" (paths, URLs) never opens the list."""
    assert slash_query("abc/h") is None
    assert slash_query("file:///x") is None


def test_filter_commands_prefix():
    matched = filter_commands(query="repl")
    names = [c.name for c in matched]
    assert "/replay" in names


def test_filter_commands_empty_returns_all():
    # 空 query = 按数量限制返回整个池（默认 limit=20；具体长度用 limit 升限）
    assert len(filter_commands(query="")) == min(len(SLASH_COMMANDS), 20)
    assert len(filter_commands(query="", limit=99)) == len(SLASH_COMMANDS)


def test_tui_ux5_entries_present():
    names = [c.name for c in SLASH_COMMANDS]
    assert "/undo" in names  # 工单 07
    assert "/skills" in names  # 工单 09
    assert "/use" in names  # 工单 09


def test_tui_ux12_yolo_entry():
    from src.slash_completion import SLASH_COMMANDS, filter_commands, slash_query

    assert "/yolo" in [c.name for c in SLASH_COMMANDS]
    assert "/yolo" in [c.name for c in filter_commands(query="yol")]
    # 尾随空格（正在打参数）→ slash_query 返回 None，不弹命令候选
    assert slash_query("/yolo ") is None
