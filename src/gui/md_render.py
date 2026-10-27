"""Markdown → Qt 富文本渲染（QLabel 文本框用）。

- md_to_qt_html：QTextDocument.setMarkdown 转 HTML，code 块套等宽+底色 span。
- mono_font：工具/参数等宽字体。
（思考块 / 工具详情由 pane.ThinkingBox / pane.ToolLineWidget 直接构造，见 pane.py）
"""
from __future__ import annotations

import re

from PySide6.QtGui import QFont, QTextDocument

_CODE_SPAN = (
    "<span style=\"font-family: Consolas, 'Courier New', monospace; "
    "background-color: #161616; color: #dddddd;\">"
)


def md_to_qt_html(md: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(md or "")
    html = doc.toHtml()

    def _pre_sub(m: re.Match[str]) -> str:
        body = m.group(1).replace("\n", "<br>")
        return _CODE_SPAN + body + "</span>"

    html = re.sub(r"<pre>(?:<code>)?(.*?)</code></pre>", _pre_sub, html, flags=re.S)
    html = re.sub(r"<pre>(.*?)</pre>", _pre_sub, html, flags=re.S)
    return html


def mono_font() -> QFont:
    f = QFont("Consolas")
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(10)
    return f
