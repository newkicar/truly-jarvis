"""明暗主题 + 持久化（工单 10；用户全局 %APPDATA%\\Jarvis\\gui.json）。

taste-skill（app-screens.md）驱动的 token 化 QSS 层：
- 暗 = true-black-flat（亮度分层抬升，色彩只落数据；导航靠标签亮度，主按钮=反相药丸），
  按 JARVIS 冷调（监视器近黑底）+ 天空蓝 HUD 面改色（accent 只在数据/激活态出现）；
- 明 = framed-sheet（着色 L 框 + 白卡片），共享同一天空蓝色系（明侧取更深一档保对比）。
- 所有组件（对话气泡/工具行/审批卡片/输入/徽章/占位/补全弹层）用 objectName 选择器
  收敛到本层，杜绝散落的内联 hex；切主题 = 换整表 QSS，零重建，全量跟随。
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Template

THEMES = ("light", "dark")
DEFAULT = "dark"

# ---------------------------------------------------------------- token 表
# 键即 QSS 模板里的 $占位。色值来自 taste-skill library/app.json 两风格
# （true-black-flat / framed-sheet），按 JARVIS 面（冷底 + 天空蓝）微调；
# 两主题共享同一 accent 色系（暗侧亮、明侧深）保证「一个产品一张脸」。
TOKENS: dict[str, dict] = {
    "dark": {
        "ground": "#0c0d0f",      # 冷近黑（监视器/代理温度）
        "surface": "#15171a",     # 卡片/白片（亮度步进）
        "raised": "#202329",      # 嵌套面板/审批卡
        "deep": "#0a0b0c",        # 预览/原值框（比底再深一档）
        "active": "#1b1e24",      # 导航选中/悬停（亮度步）
        "border": "#2a2d33",
        "rule": "#1c1f24",
        "control": "#3a3f47",
        "text": "#e8e8e8",        # 柔和（长会话）；测试契约子串
        "muted": "#b4b4b4",
        "faint": "#8a8f98",
        "accent": "#4cb3f0",      # 天空蓝 HUD（JARVIS 面；只落数据/激活）
        "positive": "#4fc386",
        "negative": "#e5566f",
        "warning": "#e5a93b",
        "ok": "#6fbf8f",         # 工具成功
        "user_bg": "#16232e",    # 冷蓝步进（「你」气泡）
        "ai_bg": "#15171a",       # （= surface，「代理」气泡）
        "primary_bg": "#e8e8e8",  # 反相主按钮（move）
        "primary_ink": "#0c0d0f",
        "primary_hover": "#d5d5d5",
        "neg_soft": "#2c1a20",
        "radius": "8",
        "radius_ctrl": "6",
    },
    "light": {
        "ground": "#f6f8f9",      # 着色冷调 L 框（framed-sheet chrome）
        "surface": "#ffffff",     # 白片/卡片
        "raised": "#f4f6f8",
        "deep": "#eef1f4",
        "active": "#e7ebee",
        "border": "#e3e6ea",
        "rule": "#eef0f3",
        "control": "#c9ccd1",
        "text": "#1a1a1a",        # 测试契约子串
        "muted": "#5d5f60",
        "faint": "#6b6b6b",
        "accent": "#2f6f9f",      # 天空蓝（明侧深一档保 3:1 白底对比）
        "positive": "#1e7b4f",
        "negative": "#c4242a",
        "warning": "#92400e",
        "ok": "#2e7d5b",
        "user_bg": "#e8f0f6",
        "ai_bg": "#ffffff",
        "primary_bg": "#1a1a1a",  # 近黑主按钮（move 的明侧）
        "primary_ink": "#ffffff",
        "primary_hover": "#333333",
        "neg_soft": "#fdecee",
        "radius": "8",
        "radius_ctrl": "6",
    },
}

# ---------------------------------------------------------------- QSS 模板
# 用 string.Template（$占位）避免 CSS 花括号转义。组件 = objectName 选择器。
_QSS = Template(r"""
QWidget {
    color: $text;
    background-color: $ground;
    font-family: "Segoe UI", "Inter", system-ui, sans-serif;
}
QMainWindow { background-color: $ground; }

/* ---- 文本：默认透明底（气泡/卡片各自 objectName 覆盖背景）---- */
QLabel { background: transparent; }
QLabel#title-sessions { color: $text; font-size: 14px; font-weight: bold; }
QLabel#status-bar { color: $muted; font-size: 12px; padding: 2px; }
QLabel#badge-mode { color: $muted; font-size: 11px; }
QLabel#badge-running { color: $warning; font-size: 11px; }
QLabel#hint-note { color: $faint; font-size: 11px; }
QLabel#report-label { color: $text; font-size: 12px; }

/* ---- 对话气泡 ---- */
QLabel#bub-user { background-color: $user_bg; color: $text; border-radius: 8px; padding: 6px; }
QLabel#bub-ai { background-color: $ai_bg; color: $text; border-radius: 8px; padding: 6px; }
QLabel#line-sub { color: $warning; font-size: 12px; }
QLabel#tool-line { color: $ok; font-size: 12px; }
QLabel#tool-line[err="true"] { color: $negative; }
QLabel#tool-detail { color: $muted; font-size: 12px; }
QLabel#thinking-body { color: $faint; font-size: 11px; }
QLabel#pane-placeholder { color: $faint; font-size: 13px; }
QFrame#thinking-box { background: transparent; }

/* ---- 会话导航（亮度分层，选中=亮度步 + 标签变亮）---- */
QListWidget { background-color: $ground; border: none; outline: 0; }
QListWidget::item { color: $muted; padding: 5px 8px; border-radius: 8px; margin: 1px 4px; }
QListWidget::item:hover { background-color: $active; color: $text; }
QListWidget::item:selected { background-color: $active; color: $text; font-weight: 500; }

/* 项目→会话树（工单 04）：与导航同一套表面语言 */
QTreeWidget { background-color: $ground; border: none; outline: 0; }
QTreeWidget::item { color: $muted; padding: 4px 6px; border-radius: 6px; margin: 1px 3px; }
QTreeWidget::item:hover { background-color: $active; color: $text; }
QTreeWidget::item:selected { background-color: $active; color: $text; font-weight: 500; }
QTreeWidget#session-list::item { color: $text; }

/* ---- 补全弹层（浮层：白片 + 1px 边）---- */
QListWidget#completion-popup {
    background-color: $surface; border: 1px solid $border; border-radius: $radius_ctrl px;
}
QListWidget#completion-popup::item { color: $text; padding: 4px 8px; border-radius: $radius_ctrl px; }
QListWidget#completion-popup::item:selected { background-color: $active; color: $text; }

/* ---- 按钮：缺省=幽灵；#btn-primary=反相（move）；#btn-danger=负色描边 ---- */
QPushButton {
    color: $text; background-color: transparent; border: 1px solid $control;
    border-radius: $radius_ctrl px; padding: 4px 12px; font-size: 13px;
}
QPushButton:hover { background-color: $active; }
QPushButton:disabled { color: $faint; background-color: transparent; }
QPushButton#btn-primary {
    color: $primary_ink; background-color: $primary_bg; border: none; font-weight: bold;
}
QPushButton#btn-primary:hover { background-color: $primary_hover; }
QPushButton#btn-primary:disabled { background-color: $control; color: $faint; }
QPushButton#btn-danger { color: $negative; border: 1px solid $negative; }
QPushButton#btn-danger:hover { background-color: $neg_soft; }
QPushButton#btn-danger:disabled { color: $faint; border: 1px solid $rule; background-color: transparent; }
QPushButton#back-pill {
    color: $ground; background-color: $accent; border: none; border-radius: 17px;
    font-size: 16px; font-weight: bold;
}
QPushButton#tool-toggle, QPushButton#thinking-toggle {
    color: $accent; background-color: transparent; border: 1px solid $control;
    border-radius: $radius_ctrl px; font-size: 11px; padding: 1px 6px;
}
QPushButton#tool-toggle:hover, QPushButton#thinking-toggle:hover { background-color: $active; }

/* ---- 输入 / 编辑器 / 预览 ---- */
QLineEdit, QPlainTextEdit {
    color: $text; background-color: $surface; border: 1px solid $control;
    border-radius: $radius_ctrl px; padding: 4px;
}
QPlainTextEdit#card-preview, QPlainTextEdit#card-orig {
    background-color: $deep; color: $muted; border: 1px solid $rule;
}

/* ---- 审批卡片（工单 04）---- */
QFrame#approval-card {
    background-color: $raised; border: 1px solid $border; border-radius: 8px;
}
QLabel#card-head { color: $warning; font-size: 14px; font-weight: bold; }
QLabel#card-label { color: $muted; }
QLabel#card-note { color: $faint; font-size: 11px; }
QLabel#card-key { color: $faint; font-size: 12px; }
QLabel#card-done { color: $positive; font-weight: bold; }
QLabel#card-deny { color: $negative; font-weight: bold; }

/* ---- 图片附件条 ---- */
QLabel#image-thumb { border: 1px solid $control; border-radius: 6px; background: $surface; }
QPushButton#img-remove { color: $faint; background: transparent; border: none; font-size: 11px; }

/* ---- 滚动区 / 菜单栏 / 状态栏 ---- */
QScrollArea { background-color: $ground; border: none; }
QMenuBar { background-color: $ground; color: $text; }
QMenuBar::item { background: transparent; padding: 4px 8px; }
QMenuBar::item:selected { background-color: $active; }
QStatusBar { background-color: $ground; color: $muted; }

/* ---- 弹窗 / 提示 ---- */
QDialog { background-color: $ground; }
QMessageBox { background-color: $surface; }
QMenu { background-color: $surface; color: $text; border: 1px solid $border; }
QMenu::item { padding: 4px 20px; }
QMenu::item:selected { background-color: $active; color: $text; }
QMenu::separator { height: 1px; background-color: $rule; margin: 3px 8px; }
QToolTip {
    background-color: $raised; color: $text; border: 1px solid $border;
    padding: 4px; font-size: 12px;
}

/* ---- 滚动条（两向，圆 thumb）---- */
QScrollBar:vertical { background: $ground; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $control; min-height: 24px; border-radius: 6px; margin: 2px; }
QScrollBar::handle:vertical:hover { background: $muted; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: $ground; }
QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical { background: $control; width: 10px; height: 10px; }
QScrollBar:horizontal { background: $ground; height: 12px; margin: 0; }
QScrollBar::handle:horizontal { background: $control; min-width: 24px; border-radius: 6px; margin: 2px; }
QScrollBar::handle:horizontal:hover { background: $muted; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: $ground; }

/* 兼容遗留选择器（无 widget 再设 #hint，保留无害） */
QLabel#hint { color: $muted; }
""")


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


def tokens(name: str) -> dict:
    """某主题的命名 token（组件构造期读色用；缺省回落 dark）。"""
    return TOKENS[name if name in TOKENS else DEFAULT]


def stylesheet(theme: str) -> str:
    t = TOKENS[theme if theme in TOKENS else DEFAULT]
    return _QSS.safe_substitute(t)


_applied: str = DEFAULT


def apply_theme(app, theme: str) -> None:
    global _applied
    _applied = theme if theme in THEMES else DEFAULT
    app.setStyleSheet(stylesheet(_applied))


def applied_theme() -> str:
    """最近一次 apply_theme 的主题（组件构造期取色源）。"""
    return _applied


def current_tokens() -> dict:
    return tokens(_applied)


def toggle_theme(home: Path | None = None) -> str:
    """切到相反主题并持久化，返回新主题。"""
    cur = load_theme(home)
    nxt = "light" if cur == "dark" else "dark"
    save_theme(nxt, home)
    return nxt
