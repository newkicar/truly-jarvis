"""审批卡片左右对比 diff（codex 式 side-by-side）。

左栏 = 原值，右栏 = 新值，行行一一对应：
删除行：左标红、右留空；添加行：左留空、右标绿；修改行：左标红、右标绿；
相等行 = 普通显示。
"""
from __future__ import annotations

import difflib

from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from src.gui import md_render, theme

__all__ = ["aligned_diff", "SideBySideDiff"]

_ELL = "\u2026"


def aligned_diff(old, new, max_lines=300):
    """逐行对齐 old/new，返回 [(mark, left, right)] 行列表。

    mark 取值：' '(相等) / '-'(删除) / '+'(新增) / '~'(修改) / '\u2026'(截断)：
    equal 行 (l,l)；delete 行 (l,"")；insert 行 ("",r)；replace 块按 zip 补齐
    （两侧有内容='~'修改，仅一侧有内容=删/增）；超出 max_lines 截断，末行为截断标记。
    """
    old_lines = (old or "").split("\n")
    new_lines = (new or "").split("\n")
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    rows = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                rows.append((" ", old_lines[k], new_lines[j1 + (k - i1)]))
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append(("-", old_lines[k], ""))
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append(("+", "", new_lines[k]))
        else:  # replace：zip 补齐（列表 padding，两侧等长逐行配对比）
            chunk_o = old_lines[i1:i2]
            chunk_n = new_lines[j1:j2]
            pad = max(len(chunk_o), len(chunk_n))
            chunk_o = chunk_o + [""] * (pad - len(chunk_o))
            chunk_n = chunk_n + [""] * (pad - len(chunk_n))
            for k in range(pad):
                left, right = chunk_o[k], chunk_n[k]
                if left and right:
                    rows.append(("~", left, right))
                elif left:
                    rows.append(("-", left, ""))
                else:
                    rows.append(("+", "", right))
    if len(rows) > max_lines:
        rows = rows[: max_lines - 1] + [(_ELL, _ELL, _ELL)]
    return rows


class SideBySideDiff(QFrame):
    """两栏并排：垂直滚动同步；行色随当前主题（theme.current_tokens）。"""

    def __init__(self, old, new, max_lines=300, parent=None):
        super().__init__(parent)
        self.setObjectName("diff-view")
        self.setMinimumWidth(0)
        self._syncing = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        self._left = self._make_pane()
        self._right = self._make_pane()
        outer.addLayout(self._add_column("\u539f\u503c", self._left), 1)
        outer.addLayout(self._add_column("\u65b0\u503c", self._right), 1)

        rows = aligned_diff(old, new, max_lines)
        self._fill(self._left, rows, "left")
        self._fill(self._right, rows, "right")

        lb = self._left.verticalScrollBar()
        rb = self._right.verticalScrollBar()
        lb.valueChanged.connect(lambda v: self._sync(lb, rb, v))
        rb.valueChanged.connect(lambda v: self._sync(rb, lb, v))

    def _make_pane(self):
        pane = QPlainTextEdit()
        pane.setObjectName("diff-pane")
        pane.setFont(md_render.mono_font())
        pane.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        pane.setFixedHeight(160)
        pane.setReadOnly(True)
        pane.setMinimumWidth(0)
        return pane

    def _add_column(self, head, pane):
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        label = QLabel(head)
        label.setObjectName("diff-head")
        label.setFixedWidth(44)
        col.addWidget(label)
        col.addWidget(pane, 1)
        return col

    def _fill(self, pane, rows, side):
        tokens = theme.current_tokens()
        cur = pane.textCursor()
        pane.moveCursor(QTextCursor.MoveOperation.Start)
        pane.setPlainText("")
        for mark, left, right in rows:
            text = left if side == "left" else right
            if mark == "-":
                color = tokens["negative"] if side == "left" else tokens["text"]
            elif mark == "+":
                color = tokens["positive"] if side == "right" else tokens["text"]
            elif mark == "~":
                color = tokens["negative"] if side == "left" else tokens["positive"]
            elif mark == _ELL:
                color = tokens["faint"]
            else:
                color = tokens["text"]
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            cur.mergeCharFormat(fmt)
            cur.insertText(text)
            cur.insertBlock()

    def _sync(self, src, dst, value):
        if self._syncing:
            return
        self._syncing = True
        dst.setValue(value)
        self._syncing = False
