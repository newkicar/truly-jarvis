"""GUI 主题体系（WP3）单测：7 主题 token 表完整 / 样式表替换 / 循环切换 / 持久化。

纪律：offscreen Qt；.scratch/ 下自建目录（勿用 tmp_path/tempfile，WinError 5 中毒）；
home 注入走 JARVIS_GUI_HOME / 函数 home 参。
"""
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.gui import theme

ALL_THEMES = (
    "dark",
    "light",
    "tokyo-night",
    "nord",
    "gruvbox",
    "dracula",
    "catppuccin",
)

REQUIRED_KEYS = (
    "ground", "surface", "raised", "deep", "active", "border",
    "rule", "control", "text", "muted", "faint", "accent",
    "positive", "negative", "warning", "ok", "user_bg", "ai_bg",
    "primary_bg", "primary_ink", "primary_hover", "neg_soft",
    "radius", "radius_ctrl",
)

GROUND_HEX = {
    "tokyo-night": "#1a1b26",
    "nord": "#2e3440",
    "gruvbox": "#1d2021",
    "dracula": "#282a36",
    "catppuccin": "#1e1e2e",
}


def _probe_home(tag: str) -> Path:
    d = Path(".scratch") / "themes_probe" / tag
    if d.exists():
        for f in d.iterdir():
            f.unlink()
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.mark.parametrize("name", ALL_THEMES)
def test_all_themes_carry_full_token_table(name):
    t = theme.tokens(name)
    missing = [k for k in REQUIRED_KEYS if k not in t]
    assert not missing, f"{name} missing keys: {missing}"
    assert all(isinstance(v, str) for v in t.values())


@pytest.mark.parametrize("name", ALL_THEMES)
def test_stylesheet_fully_substituted_per_theme(name):
    qss = theme.stylesheet(name)
    assert "$" not in qss, f"{name} stylesheet 残留未替换占位符"


def test_theme_order_contract():
    assert theme.THEMES == ALL_THEMES
    assert theme.THEMES[0] == "dark"
    assert theme.THEMES[1] == "light"
    assert len(theme.THEMES) == 7


@pytest.mark.parametrize("name,ground", sorted(GROUND_HEX.items()))
def test_ground_hex_anchors(name, ground):
    assert theme.tokens(name)["ground"] == ground


@pytest.mark.parametrize("name", ALL_THEMES)
def test_theme_keys_sane(name):
    t = theme.tokens(name)
    assert t["text"] != t["ground"]
    assert t["primary_bg"] != t["primary_ink"]


def test_toggle_cycle_wraps_to_dark():
    home = _probe_home("wrap")
    theme.save_theme("catppuccin", home)
    assert theme.toggle_theme(home) == "dark"


def test_toggle_sequence_from_fresh_home():
    home = _probe_home("seq")
    assert theme.load_theme(home) == "dark"
    assert theme.toggle_theme(home) == "light"  # ticket10 契约（dark→light）
    assert theme.toggle_theme(home) == "tokyo-night"
    assert theme.toggle_theme(home) == "nord"


def test_unknown_saved_theme_falls_back_to_default():
    home = _probe_home("unknown")
    (home / "gui.json").write_text('{"theme": "solarized"}', encoding="utf-8")
    assert theme.load_theme(home) == "dark"


def test_apply_theme_tokyo_stylesheet(qapp):
    try:
        theme.apply_theme(qapp, "tokyo-night")
        assert theme.applied_theme() == "tokyo-night"
        assert "#1a1b26" in qapp.styleSheet()
    finally:
        theme.apply_theme(qapp, "dark")
