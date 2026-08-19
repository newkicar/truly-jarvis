"""CopyableRichLog 与剪贴板辅助测试。"""
from textual.selection import Selection
from textual.geometry import Offset

from src.tui_log import CopyableRichLog, copy_text_to_system_clipboard


def test_copyable_rich_log_get_selection_extracts_plain_text():
    log = CopyableRichLog(markup=True)
    # 不 mount 也可测 get_selection（lines 由 write 填充；此处直接造 strip）
    from textual.strip import Strip
    from rich.segment import Segment

    log.lines = [
        Strip([Segment("  - session-abc123")]),
        Strip([Segment("  - default")]),
    ]
    selected = log.get_selection(
        Selection.from_offsets(Offset(4, 0), Offset(20, 0))
    )
    assert selected is not None
    assert selected[0] == "session-abc123"


def test_copy_text_to_system_clipboard_no_crash():
    # 非 Windows 或未打开剪贴板时返回 False 即可，不应抛错
    assert copy_text_to_system_clipboard("") in (True, False)
