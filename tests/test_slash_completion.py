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
