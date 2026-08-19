"""TUI 日志区：支持鼠标拖选 + Ctrl+Shift+C 复制。"""
from __future__ import annotations

import sys

from textual.selection import Selection
from textual.widgets import RichLog


def copy_text_to_system_clipboard(text: str) -> bool:
    """写入系统剪贴板；Windows 用 Win32 API，其它平台走 Textual OSC 52 即可。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            payload = text.encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
            if not handle:
                return False
            locked = kernel32.GlobalLock(handle)
            if not locked:
                return False
            ctypes.memmove(locked, payload, len(payload))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                return False
        finally:
            user32.CloseClipboard()
        return True
    except Exception:
        return False


class CopyableRichLog(RichLog):
    """RichLog + 文本选择（供 screen.copy_text / 自定义复制快捷键）。"""

    ALLOW_SELECT = True

    def focus_on_click(self) -> bool:
        """允许拖选文本，但不抢输入框焦点。"""
        return False

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        if not self.lines:
            return None
        plain_lines = [
            "".join(text for text, _style, control in strip if not control)
            for strip in self.lines
        ]
        text = "\n".join(plain_lines)
        if not text:
            return None
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()
