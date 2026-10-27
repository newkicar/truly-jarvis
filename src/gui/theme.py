"""明暗主题 + 持久化（工单 10；用户全局 %APPDATA%\\Jarvis\\gui.json）。

QSS 变量风格：主窗口/面板用 $accent 等少数语义色；对话区块（用户蓝/AI 深底）
两主题下保持对比度。切主题零重建（仅 applyStyle 到 central）。
"""
from __future__ import annotations

import json
from pathlib import Path

THEMES = ("light", "dark")
DEFAULT = "dark"

_DARK = """
QWidget { color: #e8e8e8; }
QListWidget { color: #e8e8e8; }
QLabel#hint { color: #9aa7b4; }
"""

_LIGHT = """
QWidget { color: #1a1a1a; }
QListWidget { color: #1a1a1a; }
QLabel#hint { color: #555555; }
"""


def gui_home() -> Path:
    import os

    env = os.environ.get("JARVIS_GUI_HOME")
    if env:
        return Path(env)
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(appdata) / "Jarvis"


def theme_path(home: Path | None = None) -> Path:
    return (home or gui_home()) / "gui.json"


def load_theme(home: Path | None = None) -> str:
    p = theme_path(home)
    if not p.exists():
        return DEFAULT
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        v = str(data.get("theme", DEFAULT))
        return v if v in THEMES else DEFAULT
    except (json.JSONDecodeError, OSError):
        return DEFAULT


def save_theme(theme: str, home: Path | None = None) -> Path:
    if theme not in THEMES:
        raise ValueError(f"unknown theme: {theme!r}")
    p = theme_path(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"theme": theme}, ensure_ascii=False), encoding="utf-8")
    return p


def stylesheet(theme: str) -> str:
    return _LIGHT if theme == "light" else _DARK


def apply_theme(app, theme: str) -> None:
    app.setStyleSheet(stylesheet(theme))


def toggle_theme(home: Path | None = None) -> str:
    """切到相反主题并持久化，返回新主题。"""
    cur = load_theme(home)
    nxt = "light" if cur == "dark" else "dark"
    save_theme(nxt, home)
    return nxt
