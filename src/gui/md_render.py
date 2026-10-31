"""Markdown → Qt 富文本渲染（QLabel 文本框用）。

- md_to_qt_html：QTextDocument.setMarkdown 转 HTML，code 块套等宽+底色 span，
  长 token 强制断行（横向不溢出对话框区域）。
- soft_break：纯文本长段强制断行（保留既有换行；超限段每 every 字符硬切）。
- soft_break_html：HTML 富文本纯文本段强制插入 <br>（标签原样透传）。
- mono_font：工具/参数等宽字体。
（思考块 / 工具详情由 pane.ThinkingBox / pane.ToolLineWidget 直接构造，见 pane.py）
"""
from __future__ import annotations

import re

from PySide6.QtGui import QFont, QTextDocument

from src.gui import theme

__all__ = ["md_to_qt_html", "mono_font", "soft_break", "soft_break_html"]


def soft_break(text: str, every: int = 60) -> str:
    """长无空格 token 每 every 字符强制断行。

    既有换行原样保留；超限段每 every 字符硬切。PySide6 6.12 的 QLabel 未暴露
    WordWrapMode.BreakWord：不换行长 token 会把 minimumSizeHint 顶到数千 px，
    显式断行后 wordWrap 生效、最小宽塌缩（2026-10-28 报障「审批栏太宽」同源）。
    """
    out: list[str] = []
    for seg in str(text).split("\n"):
        while len(seg) > every:
            out.append(seg[:every])
            seg = seg[every:]
        out.append(seg)
    return "\n".join(out)


def soft_break_html(html: str, every: int = 80) -> str:
    """HTML 富文本里的纯文本段强制插入 <br>（标签原样透传，绝不断入标签内）。"""
    parts = re.split(r"(<[^>]*>)", html or "")
    out: list[str] = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 奇数段 = 标签，原样
            out.append(part)
            continue
        while len(part) > every:
            out.append(part[:every])
            out.append("<br>")
            part = part[every:]
        out.append(part)
    return "".join(out)


def _code_span() -> str:
    """code 块底色 span（随当前主题 token 取色，暗深底亮字 / 明浅底深字）。"""
    tok = theme.current_tokens()
    return (
        "<span style=\"font-family: Consolas, 'Courier New', monospace; "
        f"background-color: {tok['deep']}; color: {tok['text']};\">"
    )


def md_to_qt_html(md: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(md or "")
    html = doc.toHtml()

    def _pre_sub(m: re.Match[str]) -> str:
        # 逐源码行 60 字断行 + 既有换行 → <br>；Qt 富文本只认 <br> 不认裸 \n
        wrapped = [
            soft_break(line, 60).replace("\n", "<br>") for line in m.group(1).split("\n")
        ]
        body = "<br>".join(wrapped)
        return _code_span() + body + "</span>"

    html = re.sub(r"<pre>(?:<code>)?(.*?)</code></pre>", _pre_sub, html, flags=re.S)
    html = re.sub(r"<pre>(.*?)</pre>", _pre_sub, html, flags=re.S)
    # 长 token（URL/哈希/单行代码）横向不溢出：纯文本段 80 字强制 <br>
    return soft_break_html(html, 80)


def mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(10)
    return f