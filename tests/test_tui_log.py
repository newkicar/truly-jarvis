"""CopyableRichLog 与剪贴板辅助测试。"""
from textual.geometry import Offset
from textual.selection import Selection
from textual.strip import Strip
from rich.segment import Segment

from src.tui_log import CopyableRichLog, copy_text_to_system_clipboard, renderable_to_plain


def test_renderable_to_plain_strips_markup():
    assert renderable_to_plain("[bold]hi[/bold]") == "hi"
    assert renderable_to_plain("plain") == "plain"


def test_copyable_rich_log_get_selection_extracts_plain_text():
    log = CopyableRichLog(markup=True)
    log.lines = [
        Strip([Segment("  - session-abc123")]),
        Strip([Segment("  - default")]),
    ]
    log._plain_lines = ["  - session-abc123", "  - default"]
    selected = log.get_selection(Selection.from_offsets(Offset(4, 0), Offset(20, 0)))
    assert selected is not None
    assert selected[0] == "session-abc123"


def test_copyable_rich_log_plain_text_from_lines():
    log = CopyableRichLog(markup=True)
    log.lines = [Strip([Segment("line one")]), Strip([Segment("line two")])]
    assert log.plain_text() == "line one\nline two"


def test_copy_text_to_system_clipboard_no_crash():
    assert copy_text_to_system_clipboard("") is False
    assert copy_text_to_system_clipboard("x") in (True, False)
