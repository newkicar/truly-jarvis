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
    """输入框上方候选弹层：候选来自 OverlayState；点击 / Tab（输入框侧）选中后 accept。

    形态（2026-10-28）：**Qt.ToolTip + NoFocus** 无边框浮层——不抢键盘焦点
    （Qt.Popup 会独占键盘，输入框敲一个字就被打断，须 Esc 才能继续打字），
    无标题栏/窗口按钮；点外部自动隐藏（tooltip 原生语义）。
    """

    def __init__(self, on_accept, parent=None) -> None:
        super().__init__(parent)
        self._on_accept = on_accept
        self._last_shown: tuple[tuple[str, ...], bool] | None = None
        self.setObjectName("completion-popup")
        self.setFixedWidth(360)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWindowFlags(Qt.ToolTip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.itemClicked.connect(self._on_item_clicked)

    def show_items(self, items: tuple[SuggestionItem, ...], no_match: bool = False) -> None:
        key = (tuple((i.insert, i.label) for i in items), no_match)
        if self._last_shown == key and self.isVisible():
            return  # 候选未变且弹层仍开着不重建；被 hide 过（Tab 接受/Esc/删除）必须重显
        self._last_shown = key
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

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        """点击候选 = 接受（鼠标流；No matching 行无选中标旗，不受影响）。"""
        if item.flags() & Qt.ItemFlag.ItemIsSelectable:
            self._on_accept(item.data(_USER_ROLE))

    def accept_top(self) -> bool:
        """首个*可选*候选（No matching items 行不可选）。接受=True，无候选=False。"""
        for i in range(self.count()):
            it = self.item(i)
            if it.flags() & Qt.ItemFlag.ItemIsSelectable:
                self._on_accept(it.data(_USER_ROLE))
                return True
        return False
