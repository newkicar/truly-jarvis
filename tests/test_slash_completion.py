"""slash 命令补全测试。"""
from src.slash_completion import SLASH_COMMANDS, filter_commands, slash_query


def test_slash_query_line_start():
    assert slash_query("/his") == (0, "his")
    assert slash_query("/") == (0, "")
    assert slash_query("hello /x") is None


def test_filter_commands_prefix():
    matched = filter_commands(query="repl")
    names = [c.name for c in matched]
    assert "/replay" in names


def test_filter_commands_empty_returns_all():
    assert len(filter_commands(query="")) == len(SLASH_COMMANDS)


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
