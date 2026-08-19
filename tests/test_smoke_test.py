"""smoke_test 参数解析测试（不触网、不启 TUI）。"""
from src import smoke_test


def test_parse_smoke_argv_cli_default():
    use_tui, use_hitl, question = smoke_test.parse_smoke_argv([])
    assert use_tui is False
    assert use_hitl is False
    assert question is None


def test_parse_smoke_argv_tui_hitl():
    use_tui, use_hitl, question = smoke_test.parse_smoke_argv(["--tui-hitl"])
    assert use_tui is True
    assert use_hitl is True
    assert question is None


def test_parse_smoke_argv_cli_with_question():
    use_tui, use_hitl, question = smoke_test.parse_smoke_argv(["hello world"])
    assert use_tui is False
    assert question == "hello world"
