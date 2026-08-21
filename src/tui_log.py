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
    """写入系统剪贴板；Windows 用 Win32 API。"""
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
                kernel32.GlobalFree(handle)
                return False
            ctypes.memmove(locked, payload, len(payload))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
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
    COMPONENT_CLASSES = {"copyable-rich-log--selection"}

    DEFAULT_CSS = """
    CopyableRichLog {
        & > .copyable-rich-log--selection {
            background: $primary 35%;
            color: $text;
        }
    }
    """

    def __init__(self, *args, copy_on_select: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.copy_on_select = copy_on_select
        self._plain_lines: list[str] = []

    def focus_on_click(self) -> bool:
        """允许拖选；不抢底部输入框焦点。"""
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

    def selected_plain_text(self) -> str:
        """当前选区对应的纯文本（无选区则空串）。"""
        try:
            screen = self.screen
        except Exception:
            return ""
        if screen is None:
            return ""
        selection = screen.selections.get(self)
        if selection is None:
            return ""
        pair = self.get_selection(selection)
        if not pair:
            return ""
        return pair[0]

    def copy_selection_to_clipboard(self) -> tuple[bool, str]:
        """复制当前选区；返回 (是否写入系统剪贴板, 文本)。"""
        text = self.selected_plain_text().strip()
        if not text:
            return False, ""
        ok = copy_text_to_system_clipboard(text)
        if self.app is not None:
            self.app.copy_to_clipboard(text)
        return ok, text

    def clear_user_selection(self) -> None:
        """流式开始时清除选区。"""
        if self.app is not None and self.screen is not None:
            self.screen.clear_selection()
        self.refresh()

    def on_text_selected(self, event: events.TextSelected) -> None:
        """拖选结束后复制（等 Textual 完成选区再读，避免空剪贴板）。"""
        if not self.copy_on_select:
            return
        ok, text = self.copy_selection_to_clipboard()
        if not text:
            return
        if ok and self.app is not None:
            self.app.notify(f"已复制 {len(text)} 字符", timeout=2)
        elif self.app is not None:
            self.app.notify("复制失败，请用 Ctrl+Insert", timeout=3)
