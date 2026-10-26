"""Markdown → Qt 富文本渲染（QLabel 文本框用）。

- md_to_qt_html：QTextDocument.setMarkdown 转 HTML，code 块套等宽+底色 span。
- thinking_block_html：思考块（小字淡色，工单 06；01 预留接口）。
- tool_detail_html：工具详情展开区（等宽 args + 输出，工单 06）。
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
    f.setStyleHint(QFont.Monospace)
    f.setPointSize(10)
    return f


# ---- 工单 06 预留：思考块 / 工具详情


def thinking_block_html(text: str) -> str:
    """思考块：小字淡色（用户裁定样式），与正文明显区分。"""
    safe = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    return (
        f'<span style="color:#8a99a8; font-size:11px; font-style:italic;">'
        f'<br>{safe}</span>'
    )


def tool_detail_html(args_text: str, output_text: str, *, error: bool = False) -> str:
    """工具详情区：args + 完整输出（等宽）；错误态染红。"""
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    color = "#e57373" if error else "#c8c8c8"
    return (
        f'<span style="font-family: Consolas, \'Courier New\', monospace; '
        f'font-size:12px; color:{color};">'
        f"<br><b>args</b><br>{esc(args_text)}<br>"
        f"<br><b>output</b><br>{esc(output_text)}</span>"
    )
