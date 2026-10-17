"""标点快插面板支持模块（#02）。

主修复 = src/ime_shim.py（补 Textual win32 驱动丢弃的 UNICODE/IME 输入记录，
conhost 下输入法确认的 “ ” ‘ ’ … 等组合字符直接可输）。
本模块 = 兜底：Ctrl+. 标点快插面板（PunctPanelModal，见 tui.py）+ conhost 启动提示。
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
    ("「", "左角引号"),
    ("」", "右角引号"),
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
    """标点输入提示的 Rich markup（dim 样式；终端无关文案）。"""
    return (
        "[dim]提示：全角标点如“”‘’…通常可直接输入法输入；"
        "若个别标点仍输不进（ConPTY/IME 差异），按 Ctrl+. 打开标点快插面板选取。[/dim]"
    )


def ime_hint_line(mode: str, conhost: bool, windows_terminals: bool = False) -> str:
    """按 tui.ime_hint 配置（off/on/auto）给出标点输入提示行，不需要提示时返回 ''。

    auto：Windows 终端环境（conhost 或其他 Windows 终端，如 Windows Terminal）提示；
    on：总是提示；off：不提示；非法值回落 auto。双参调用行为不变（第三参默认 False）。
    """
    m = str(mode).strip().lower()
    if m not in ("off", "on", "auto"):
        m = "auto"
    if m == "off":
        return ""
    if m == "on":
        return ime_hint_markup()
    return ime_hint_markup() if (conhost or windows_terminals) else ""
