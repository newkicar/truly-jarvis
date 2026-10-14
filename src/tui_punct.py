"""标点快插面板支持模块（#02）。

conhost 老终端下中文标点 IME 候选窗输入不可靠；本项目不造 IME，
提供 Ctrl+. 标点快插面板（PunctPanelModal，见 tui.py）+ conhost 启动提示。
"""

from __future__ import annotations

import os
import sys

__all__ = [
    "PUNCT_ITEMS",
    "ime_hint_line",
    "ime_hint_markup",
    "is_conhost_like",
]

# 标点快插列表（中英文高频标点；字符唯一，兼作 OptionList 的 Option id）。
PUNCT_ITEMS: tuple[tuple[str, str], ...] = (
    ("，", "全角逗号"),
    ("。", "全角句号"),
    ("、", "顿号"),
    ("…", "省略号"),
    ("—", "破折号"),
    ("～", "波浪线"),
    ("“", "左双引号"),
    ("”", "右双引号"),
    ("‘", "左单引号"),
    ("’", "右单引号"),
    ("《", "左书名号"),
    ("》", "右书名号"),
    ("（", "全角左括号"),
    ("）", "全角右括号"),
    ("【", "全角左方括"),
    ("】", "全角右方括"),
    ("！", "全角叹号"),
    ("？", "全角问号"),
    ("：", "全角冒号"),
    ("；", "全角分号"),
    ("·", "间隔号"),
    (",", "半角逗号"),
    (".", "半角句号"),
    ("!", "半角叹号"),
    ("?", "半角问号"),
)


def is_conhost_like() -> bool:
    """判断当前终端是否为 legacy conhost（Windows 且无 WT_SESSION/ConEmu* 标记）。

    conhost 下中文标点 IME 候选窗输入不可靠；Windows Terminal / VSCode
    内置终端（存在 WT_SESSION）或 ConEmu 下正常，返回 False。
    """
    if sys.platform != "win32":
        return False
    if os.environ.get("WT_SESSION"):
        return False
    for key, value in os.environ.items():
        if key.lower().startswith("conemu") and value:
            return False
    return True


def ime_hint_markup() -> str:
    """conhost 标点输入提示的 Rich markup（dim 样式）。"""
    return (
        "[dim]提示：conhost 下部分中文标点 IME 候选窗不可用；"
        "按 Ctrl+. 可快插标点（，。…“”《》等）。[/dim]"
    )


def ime_hint_line(mode: str, conhost: bool) -> str:
    """按 tui.ime_hint 配置（off/on/auto）给出 conhost 提示行，不需要提示时返回 ''。

    auto：仅 conhost 环境提示；on：总是提示；off：不提示；非法值回落 auto。
    """
    m = str(mode).strip().lower()
    if m not in ("off", "on", "auto"):
        m = "auto"
    if m == "off":
        return ""
    if m == "on":
        return ime_hint_markup()
    return ime_hint_markup() if conhost else ""
