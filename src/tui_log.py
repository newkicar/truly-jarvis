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
from rich.segment import Segment
from rich.style import Style
from rich.measure import measure_renderables
from textual.geometry import Size
from textual.strip import Strip
from textual.widgets import Button, RichLog


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
        # tui-ux16 sticky scroll: 未确认写入计数 + 跳转提示 Button
        # （由 tui.py on_mount 注入；None 表示无 hint）
        self._pending_msgs: int = 0
        self._stick = True
        self._snap_scheduled = False
        self.hint: Button | None = None
        # tui-ux19: clickable tool entries (pre-rendered dual variants + splice toggle)
        self._tool_entries: list[dict] = []
        self._click_down: tuple[int, int] | None = None
        self._size_known = False  # tui-ux19: 首次 on_show（布局落定）后置 True，工具条目双变体才可预渲染

    def on_show(self, event: events.Show) -> None:
        """tui-ux19: widget 首次上屏（父布局已完成，size.width 有效）→ 工具条目双变体预渲染可用。"""
        self._size_known = True
        self._materialize_pending_entries()  # tui-ux19r2: materialize pre-layout pending entries

    def focus_on_click(self) -> bool:
        """tui-ux17: 点击日志区即聚焦（对标 opencode 列表点击聚焦模型；Textual 8.2.8
        Screen._on_click → get_focusable_widget_at + focus_on_click → set_focus 实证）。
        聚焦后 ScrollableContainer 内置键绑定生效：PgUp/PgDn 翻页、Home/End 跳顶/跳底
        （action 解析链 widget→screen→app，RichLog 无同名键，天然不冲突）；
        watch_scroll_y 的 sticky 状态机对键盘滚动同样联动（上翻自动停跟随、hint 出现）。
        拖选走 Screen 级 ALLOW_SELECT 路径，与焦点无关；点回 #input 即回到输入焦点。
        旧版 return False 导致点击永远不聚焦 → 翻页键全部失效（本条修复的遗留 bug 根因）。"""
        return True

    def render_line(self, y: int) -> Strip:
        """渲染叠加：offset meta（选区命中）+ 选区高亮底色（用户 P4：框选可见）。

        Textual 8.2.8 的 RichLog 原生 strip 不带 offset meta，
        Compositor.get_widget_and_offset_at 无法把鼠标坐标落到 (行, 列)，
        选区会塌缩成「整个 widget 全选」。这里补上字符 offset，
        并手动把 selection 组件样式叠在选区行上（RichLog 不走过 Visual 高亮路径）。
        """
        strip = super().render_line(y)
        scroll_x, scroll_y = self.scroll_offset
        content_row = scroll_y + y
        strip = strip.apply_offsets(scroll_x, content_row)
        selection = self.text_selection
        if selection is not None:
            span = selection.get_span(content_row)
            if span is not None:
                sel_style = self.get_component_rich_style(
                    "copyable-rich-log--selection", default=None
                )
                if sel_style is not None:
                    strip = self._overlay_selection(strip, span[0], span[1], sel_style)
        return strip

    @staticmethod
    def _overlay_selection(
        strip: Strip, x0: int, x1: int, sel_style: Style
    ) -> Strip:
        """把字符 span [x0, x1) 映射到 cell span 并叠加高亮样式。

        -1 表示行尾；cell 坐标经 cell_len 换算（CJK 双 cell）；
        用 Segment.divide 在 cell 切点处切段，中间段叠 sel_style。
        """
        from rich.cells import cell_len

        segments = strip._segments  # noqa: SLF001
        row_text = "".join(seg.text for seg in segments if not seg.control)
        total_cells = strip.cell_length
        x1_chars = len(row_text) if x1 < 0 else x1
        start_cell = cell_len(row_text[:x0])
        end_cell = min(cell_len(row_text[:x1_chars]), total_cells)
        if end_cell <= start_cell:
            return strip
        parts = list(Segment.divide(segments, [start_cell, end_cell]))
        new_segments: list[Segment] = []
        for idx, part in enumerate(parts):
            if idx == 1:
                for seg in part:
                    text, style, control = seg
                    if control:
                        new_segments.append(seg)
                        continue
                    new_style = (style + sel_style) if style else sel_style
                    new_segments.append(Segment(text, new_style, control))
            else:
                new_segments.extend(part)
        return Strip(Segment.simplify(new_segments), total_cells)

    def write(self, content, *args, **kwargs):
        # tui-ux16 sticky scroll（codex 交互模型）：贴底自动跟随；
        # 上翻后停跳，累计未确认新消息。显式 scroll_end（kwarg，或
        # 第 4 个位置参数 = deferred 回放形态）原样尊重。
        if "scroll_end" not in kwargs and len(args) < 4:
            if self._at_bottom() or self._stick:
                kwargs["scroll_end"] = True
            else:
                kwargs["scroll_end"] = False
                if content not in ("", None):
                    self._pending_msgs += 1
                    self._refresh_hint()
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
        self._tool_entries.clear()
        self._click_down = None
        # tui-ux16: 日志清空同时复位 sticky scroll 计数 / hint
        self._stick = True
        self._pending_msgs = 0
        self._hide_hint()
        return super().clear(*args, **kwargs)

    def _at_bottom(self, tol: int = 2) -> bool:
        """垂直方向是否贴底（容差 `tol` 行）。"""
        max_y = self.max_scroll_y
        if not max_y:
            return True
        return self.scroll_offset.y >= max(0, max_y - tol)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        # tui-ux16：滚动变化唯一统一钩子（滚轮/键盘/滚动条/程序化
        # scroll_to/end 全走这里）——贴底清 pending、隐藏 hint。
        if self._at_bottom():
            self._stick = True
            self._pending_msgs = 0
        else:
            self._stick = False
        self._refresh_hint()

    def _refresh_hint(self) -> None:
        # tui-ux16r2: hint gate = not at bottom (pending count dropped)
        if not self._at_bottom():
            self._show_hint()
        else:
            self._hide_hint()

    def _show_hint(self) -> None:
        # -visible 是本项目的「hint 可见」态；不可复用 Button 内部类名 -active：
        # Textual 8.2.8 Button._on_click 内 `if not self.has_class("-active"): self.press()`
        # 会把常驻 -active 的按钮判为「按压中」，真实鼠标点击被吞掉（点击无跳转根因）。
        hint = self.hint
        if hint is None:
            return

        hint.add_class("-visible")
        hint.refresh()

    def _hide_hint(self) -> None:
        hint = self.hint
        if hint is not None:
            hint.remove_class("-visible")
            hint.refresh()

    def jump_to_end(self) -> None:
        """点击 hint / 手动跳底：清 pending、隐 hint、滚到底。"""
        self._stick = True
        self._pending_msgs = 0
        self._hide_hint()
        self.scroll_end(animate=False, immediate=True, x_axis=False)


    def on_resize(self, event: events.Resize) -> None:
        # tui-ux16r2: in-flow sibling show/hide (ai_stream) resizes the log;
        # when sticking, re-snap to bottom after refresh so real-time
        # follow survives viewport resizes (dock/hint layout changes)
        super().on_resize(event)
        if self._stick and not self._snap_scheduled:
            self._snap_scheduled = True
            self.call_after_refresh(self._snap_after_resize)

    def _snap_after_resize(self) -> None:
        self._snap_scheduled = False
        if not self._stick:
            return
        self._pending_msgs = 0
        self.scroll_end(animate=False, immediate=True, x_axis=False)
        self._refresh_hint()

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

    def _write_variant_strips(self, text: str) -> tuple[list[Strip], int]:
        # 把一个 markup 文本折行成本 widget 宽度下的 strip 列表（对齐 RichLog 原生 write 管道）
        from rich.console import Console
        width = max(1, self.size.width)
        local = Console(width=width)
        opts = local.options
        t = Text.from_markup(text)
        measured = measure_renderables(local, opts, [t]).maximum
        render_width = max(measured, width)
        segments = list(local.render(t, opts.update_width(render_width)))
        lines = [list(ln) for ln in Segment.split_lines(segments)]
        if not lines:
            return [Strip.blank(render_width)], render_width
        strips = [s.adjust_cell_length(render_width) for s in Strip.from_lines(lines)]
        row_w = max((sum(seg.cell_length for seg in s._segments) for s in strips), default=render_width)  # noqa: SLF001
        return strips, max(render_width, row_w)

    def _materialize_pending_entries(self) -> None:
        # tui-ux19r2: materialize entries written while size was unknown -
        # splice dual variants in place, shift later entries by the row
        # delta, and re-stick to the bottom when stuck.
        for entry in self._tool_entries:
            if entry["strips"] is not None:
                continue
            collapsed, expanded = entry["pending"]
            c_strips, c_w = self._write_variant_strips(collapsed)
            e_strips, e_w = self._write_variant_strips(expanded)
            start, end = entry["start"], entry["end"]
            delta = len(c_strips) - (end - start)
            self.lines[start:end] = c_strips
            entry["strips"] = [c_strips, e_strips]
            entry["pending"] = None
            entry["end"] = start + len(c_strips)
            if delta:
                for other in self._tool_entries:
                    if other is not entry and other["start"] >= start:
                        other["start"] += delta
                        other["end"] += delta
            self._widest_line_width = max(getattr(self, "_widest_line_width", 0), c_w, e_w)
        self._line_cache.clear()
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        if self._stick:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        self._sync_plain_lines_from_strips()
        self.refresh()

    def write_tool_entry(self, collapsed: str, expanded: str) -> None:
        # tui-ux19：注册一条可点击工具条目（折叠态上屏，展开态待命）。须在 UI 线程调用。
        if getattr(self, "max_lines", None) is not None:
            self.write(collapsed)
            return
        if not self._size_known:
            # tui-ux19r2: pre-layout pending entry: plain write + register;
            # on_show materializes the dual variants in place
            start = len(self.lines)
            self.write(collapsed)
            self._tool_entries.append({
                "active": False, "start": start, "end": len(self.lines),
                "strips": None, "pending": (collapsed, expanded),
            })
            return
        c_strips, c_w = self._write_variant_strips(collapsed)
        e_strips, e_w = self._write_variant_strips(expanded)
        start = len(self.lines)
        self.lines.extend(c_strips)
        self._tool_entries.append({"active": False, "start": start, "end": start + len(c_strips), "strips": [c_strips, e_strips]})
        self._widest_line_width = max(getattr(self, "_widest_line_width", 0), c_w, e_w)
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        if self._at_bottom() or self._stick:
            self.scroll_end(animate=False, immediate=True, x_axis=False)
        else:
            self._pending_msgs += 1
            self._refresh_hint()
        self._sync_plain_lines_from_strips()
        self.refresh()

    def _toggle_tool_entry(self, index: int) -> None:
        entry = self._tool_entries[index]
        if entry["strips"] is None:
            # tui-ux19r2: pending entry not materialized yet (on_show has not
            # fired): ignore the click instead of crashing
            return
        new_strips = entry["strips"][0 if entry["active"] else 1]
        old_y = int(self.scroll_offset.y)
        start, end = entry["start"], entry["end"]
        delta = len(new_strips) - (end - start)
        self.lines[start:end] = new_strips
        entry["active"] = not entry["active"]
        entry["end"] = start + len(new_strips)
        for other in self._tool_entries:
            if other is not entry and other["start"] >= end:
                other["start"] += delta
                other["end"] += delta
        self._line_cache.clear()
        self.virtual_size = Size(self._widest_line_width, len(self.lines))
        if self._stick or self._at_bottom():
            self.jump_to_end()
        else:
            target = min(max(old_y + delta, 0), self.max_scroll_y)
            self.scroll_to(0, target, animate=False, immediate=True)
        self._sync_plain_lines_from_strips()
        self.refresh()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # 记录按下位置，区分单点击与拖选（拖选交给复制路径）
        if event.widget is self and event.button == 1:
            self._click_down = (int(event.x), int(event.y))
        else:
            self._click_down = None

    def on_click(self, event: events.Click) -> None:
        # 单点击命中工具条目 → 展开/收起（对标 codex/opencode 点击详情）
        if event.widget is not self or event.button != 1:
            return
        if getattr(event, "chain", 1) != 1:
            return
        down = self._click_down
        self._click_down = None
        if down is None:
            return
        if abs(int(event.x) - down[0]) > 1 or abs(int(event.y) - down[1]) > 1:
            return
        content_row = int(self.scroll_offset.y) + int(event.y)
        for idx, entry in enumerate(self._tool_entries):
            if entry["start"] <= content_row < entry["end"]:
                self._toggle_tool_entry(idx)
                return
        self._click_down = None


    # 拖选松开自动复制不在本 widget 实现：Textual 8.2.8 的 TextSelected 只由
    # Screen 在 MouseUp 时 post（bubble=True，路径 Screen→App），widget 级
    # handler 收不到事件。行为统一挂在 JarvisApp.on_text_selected（src/tui.py）。
