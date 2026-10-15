"""TUI 日志区：纯文本缓冲 + 鼠标拖选 + 复制（CMD 友好）。"""
from __future__ import annotations

import os
import sys
import time
from io import StringIO

from rich.console import Console
from rich.text import Text
from textual import events
from textual.selection import Selection
from textual.widgets import RichLog


def copy_via_win32(text: str, attempts: int = 2) -> bool:
    """Win32 写系统剪贴板（OpenClipboard 失败时短暂等待后重试——剪贴板可能瞬时被占用）。"""
    if not text or sys.platform != "win32":
        return False
    try:
        import ctypes

        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        for _ in range(max(1, attempts)):
            if not user32.OpenClipboard(None):
                time.sleep(0.15)
                continue
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
                return True
            finally:
                user32.CloseClipboard()
    except Exception:  # noqa: BLE001
        return False
    return False


def copy_via_powershell(text: str, timeout: float = 6.0) -> bool:
    """PowerShell Set-Clipboard 兜底（Win32 路径不可用时，如 conhost 权限受限）。

    文本写临时 UTF-8 文件、路径经环境变量传给子进程——避开命令行引号/编码陷阱。
    """
    if not text or sys.platform != "win32":
        return False
    import subprocess
    import tempfile

    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="jarvis-clip-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        env = {**os.environ, "JARVIS_CLIP_FILE": tmp}
        script = (
            "$c = [IO.File]::ReadAllText($env:JARVIS_CLIP_FILE, [Text.Encoding]::UTF8); "
            "Set-Clipboard -Value $c"
        )
        result = subprocess.run(  # noqa: S603
            ["powershell", "-NoProfile", "-NoLogo", "-Command", script],
            capture_output=True,
            timeout=timeout,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def copy_text_to_system_clipboard(text: str) -> bool:
    """写入系统剪贴板（级联：Win32 重试 → PowerShell 兜底）；均失败返回 False。"""
    if not text:
        return False
    if sys.platform != "win32":
        return False
    if copy_via_win32(text):
        return True
    return copy_via_powershell(text)


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

    # 拖选松开自动复制不在本 widget 实现：Textual 8.2.8 的 TextSelected 只由
    # Screen 在 MouseUp 时 post（bubble=True，路径 Screen→App），widget 级
    # handler 收不到事件。行为统一挂在 JarvisApp.on_text_selected（src/tui.py）。
