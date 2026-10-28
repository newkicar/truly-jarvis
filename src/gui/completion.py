"""输入补全（工单 10）：@ 路径 · / 命令 · /use skill 模糊 —— 内核复用 tui_completion。

多行输入支持：只看光标行（line_projection），接受建议只改光标行再重建全文
（apply_suggestion_on_line，内核既有纯函数）。Tab 接受、点击接受。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem

_USER_ROLE = Qt.ItemDataRole.UserRole

from src import tui_completion
from src.tui_completion import OverlayState, SuggestionItem


def rowcol_from_cursor(widget) -> tuple[int, int]:
    """QPlainTextEdit 光标 → (row, col)。纯映射。"""
    tc = widget.textCursor()
    return tc.blockNumber(), tc.positionInBlock()


def set_cursor_pos(widget, row: int, col: int) -> None:
    doc = widget.document()
    block = doc.findBlockByNumber(max(0, row))
    if block.isValid():
        tc = widget.textCursor()
        tc.setPosition(block.position() + max(0, col))
        widget.setTextCursor(tc)


def resolve_for_input(
    widget,
    *,
    skills,
    config,
) -> OverlayState:
    """光标行补全解析（/ 命令 · /use skill 模糊 · @ 路径；workspace 优先语义不变）。"""
    text = widget.toPlainText()
    row, col = rowcol_from_cursor(widget)
    line, line_col = tui_completion.line_projection(text, (row, col))
    return tui_completion.resolve_overlay_state(
        line,
        line_col,
        vault_path=config.vault_path,
        workspace_root=config.project_root,
        memories_root=config.memory_dir,
        skills=list(skills or []),
    )


def accept_suggestion(
    widget,
    state: OverlayState,
    insert: str,
) -> bool:
    """接受建议：只改光标行，重建全文并置光标（Tab/点击共用）。"""
    if state.kind == "none" or not state.items:
        return False
    text = widget.toPlainText()
    row, col = rowcol_from_cursor(widget)
    new_text, (new_row, new_col) = tui_completion.apply_suggestion_on_line(
        text, (row, col), state.at_index, insert
    )
    widget.setPlainText(new_text)
    set_cursor_pos(widget, new_row, new_col)
    return True


def has_query_no_match(widget, state: OverlayState) -> bool:
    """弹层该显示「No matching items」行：kind 非 none 且候选为空、且用户确实
    输入了查询串（空查询 = 全量清单，不算无匹配）。"""
    if state.kind == "none" or state.items:
        return False
    text = widget.toPlainText()
    row, col = rowcol_from_cursor(widget)
    line, line_col = tui_completion.line_projection(text, (row, col))
    q = line[state.at_index + 1 : line_col]
    return len(q.strip()) > 0


class CompletionPopup(QListWidget):
    """输入框上方候选弹层：候选来自 OverlayState；鼠标/键盘选中后 accept。

    形态（2026-10-28 规格）：Qt.Popup 无边框浮层（无标题栏/最小化/关闭按钮，
    失焦自动隐藏），跟随 / @ 输入出现、删除即消失（hide 由 owner 驱动）。
    """

    def __init__(self, on_accept, parent=None) -> None:
        super().__init__(parent)
        self._on_accept = on_accept
        self.setFixedWidth(360)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 无标题栏/窗口按钮；点击外部或失焦自动隐藏（tooltip 式弹层）
        self.setWindowFlags(Qt.Popup)

    def show_items(self, items: tuple[SuggestionItem, ...], no_match: bool = False) -> None:
        self.clear()
        for it in items:
            item = QListWidgetItem(f"{it.label}   [{it.insert}]")
            item.setData(_USER_ROLE, it.insert)
            item.setToolTip(it.hint or "")
            self.addItem(item)
        if no_match and not items:
            miss = QListWidgetItem("No matching items")
            miss.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选不可点
            self.addItem(miss)
        self.setVisible(bool(items) or no_match)

    def accept_top(self) -> None:
        it = self.currentItem() or (self.item(0) if self.count() else None)
        if it is not None:
            self._on_accept(it.data(_USER_ROLE))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        from PySide6.QtCore import Qt

        if e.key() in (Qt.Key_Tab, Qt.Key_Return, Qt.Key_Enter):
            self.accept_top()
        elif e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)
