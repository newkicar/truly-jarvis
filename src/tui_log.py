"""TUI 日志区：纯文本缓冲 + 鼠标拖选 + 复制（CMD 友好）。"""
from __future__ import annotations

import sys
from io import StringIO

from rich.console import Console
from rich.text import Text
from textual import events
from textual.selection import Selection
from textual.widgets import RichLog


def copy_text_to_system_clipboard(text: str) -> bool:
    """写入系统剪贴板；Windows 用 Win32 API，其它平台走 Textual OSC 52 即可。"""
    if not text:
        return False
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


def renderable_to_plain(content: object) -> str:
    """把 RichLog.write 的内容转为可复制的纯文本（单行或多行）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return Text.from_markup(content).plain if "[" in content and "]" in content else content
    buf = StringIO()
    Console(file=buf, width=120, legacy_windows=False, highlight=False).print(content)
    return buf.getvalue().rstrip("\n")


class CopyableRichLog(RichLog):
    """RichLog + 纯文本缓冲 + 稳定选区（对标 OpenCode 方案 2）。"""

    ALLOW_SELECT = True

    def __init__(self, *args, copy_on_select: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.copy_on_select = copy_on_select
        self._plain_lines: list[str] = []

    def focus_on_click(self) -> bool:
        """允许在日志区拖选，但不抢输入框焦点。"""
        return False

    def write(self, content, *args, **kwargs):
        result = super().write(content, *args, **kwargs)
        plain = renderable_to_plain(content)
        if plain:
            for line in plain.splitlines() or [""]:
                self._plain_lines.append(line)
        elif plain == "" and content == "":
            self._plain_lines.append("")
        self._sync_plain_lines_from_strips()
        return result

    def clear(self, *args, **kwargs):
        self._plain_lines.clear()
        return super().clear(*args, **kwargs)

    def _sync_plain_lines_from_strips(self) -> None:
        """与 RichLog 渲染行对齐（wrap 后每 strip 一行）。"""
        if not self.lines:
            return
        self._plain_lines = [
            "".join(text for text, _style, control in strip if not control)
            for strip in self.lines
        ]

    def plain_text(self) -> str:
        self._sync_plain_lines_from_strips()
        return "\n".join(self._plain_lines)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = self.plain_text()
        if not text:
            return None
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        # 不 clear _line_cache：CMD 下会导致选区闪烁/失效
        self.refresh()

    def clear_user_selection(self) -> None:
        """流式开始时清除选区，避免 copy 后无法再选。"""
        if self.app is not None:
            self.screen.clear_selection()
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if event.button != 1 or not self.copy_on_select:
            return
        selected = self.screen.get_selected_text()
        if not selected or not selected.strip():
            return
        text = selected.strip()
        copy_text_to_system_clipboard(text)
        if self.app is not None:
            self.app.copy_to_clipboard(text)
            self.app.notify("已复制选中文本", timeout=2)
        self.screen.clear_selection()
