from src.tui_format import format_todos_panel


def test_format_todos_panel_empty():
    assert format_todos_panel([]) == ""
    assert format_todos_panel(None) == ""


def test_format_todos_panel_renders_statuses():
    text = format_todos_panel(
        [
            {"content": "查资料", "status": "completed"},
            {"content": "写总结", "status": "in_progress"},
            {"content": "发邮件", "status": "pending"},
        ]
    )
    assert "Tasks" in text
    assert "查资料" in text
    assert "写总结" in text
    assert "发邮件" in text
