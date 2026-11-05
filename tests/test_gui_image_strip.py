"""工单 07 — 图片附件条：纯函数载荷 + 部件 + 粘贴拦截 + 多模态提交（offscreen）。"""
import base64
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gui.image_strip import build_image_submit


# 1x1 红点 PNG（预编码，避免测试生成图片的依赖）
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
)


def _png_path(tmp_dir: str, name: str = "i.png") -> str:
    from pathlib import Path

    p = Path(tmp_dir) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_TINY_PNG)
    return str(p)


def _tmp_dir() -> str:
    import uuid

    from tests.gui_fakes import TEST_ROOT

    d = TEST_ROOT / f"img-{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    return str(d)


# ---------------------------------------------------------------- 纯函数载荷
def test_build_image_submit_no_images_passthrough():
    ui, fb, text = build_image_submit("你好", [])
    assert ui is None and fb is None and text == "你好"


def test_build_image_submit_with_images_multimodal_parts():
    d = _tmp_dir()
    p1, p2 = _png_path(d, "a.png"), _png_path(d, "b.png")
    ui, fb, text = build_image_submit("看两张图", [p1, p2])
    assert text == "看两张图"  # 展示文本保持原文
    assert isinstance(ui, list)
    types = [x["type"] for x in ui]
    assert types.count("image_url") == 2 and "text" in types
    assert all(x["image_url"]["url"].startswith("data:image/png;base64,") for x in ui if x["type"] == "image_url")
    # fallback = 路径引用（auto 拒图回落）
    assert "图片 #1 路径" in fb and p1 in fb and p2 in fb


def test_build_image_submit_big_image_falls_to_text_note():
    d = _tmp_dir()
    p = _png_path(d)
    import src.clipboard_image as ci

    orig = ci.IMAGE_MAX_BYTES
    ci.IMAGE_MAX_BYTES = 4  # 强制「过大」
    try:
        ui, fb, _ = build_image_submit("x", [p])
        joined = " ".join(str(x) for x in ui)
        assert "超过" in joined  # 过大图 → 文字说明（既有语义）
    finally:
        ci.IMAGE_MAX_BYTES = orig


# ---------------------------------------------------------------- 部件（offscreen）
def test_image_strip_add_remove_clear(qtbot):
    from src.gui.image_widgets import ImageStrip

    d = _tmp_dir()
    p = _png_path(d)
    strip = ImageStrip()
    qtbot.addWidget(strip)
    assert not strip.isVisible()
    strip.add_image(p)
    assert strip.isVisible() and strip.paths() == [p]
    strip.add_image(p)  # 重复去重
    assert strip.paths() == [p]
    strip.remove_image(p)
    assert not strip.isVisible() and strip.paths() == []
    strip.add_image(p)
    strip.clear()
    assert strip.paths() == []


def test_window_paste_clipboard_image(qapp):
    """Ctrl+V 剪贴板图 → 附件条（MainWindow._try_image_paste）。"""
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication

    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter
    from tests.gui_fakes import new_home, cleanup_home
    from tests.test_gui_presenter import _fake_runtime

    home = new_home()
    try:
        rt = _fake_runtime()
        presenter = GuiPresenter(rt, UiBridge())
        win = MainWindow(presenter, presenter.bridge)
        qapp.clipboard().clear()
        img = QImage(4, 4, QImage.Format_ARGB32)
        img.fill(0xFF336699)
        qapp.clipboard().setImage(img)
        assert win._try_image_paste() is True
        assert len(win.image_strip.paths()) == 1
        # 再粘一次（同一剪贴板图）= 新临时文件 → 第二条附件（用户有意连粘）
        assert win._try_image_paste() is True
        assert len(win.image_strip.paths()) == 2
    finally:
        cleanup_home(home)


def test_window_paste_image_path_text(qapp):
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter
    from tests.gui_fakes import new_home, cleanup_home
    from tests.test_gui_presenter import _fake_runtime

    home = new_home()
    d = _tmp_dir()
    p = _png_path(d)
    try:
        rt = _fake_runtime()
        presenter = GuiPresenter(rt, UiBridge())
        win = MainWindow(presenter, presenter.bridge)
        qapp.clipboard().setText(p)
        assert win._try_image_paste() is True
        assert p in win.image_strip.paths()
    finally:
        cleanup_home(home)


def test_submit_with_image_builds_multimodal_payload(qapp, monkeypatch):
    """发送带图消息：presenter.start_turn 收到 user_input=多模态 parts + 路径引用 fallback。"""
    from src.gui.events import UiBridge
    from src.gui.main_window import MainWindow
    from src.gui.runtime import GuiPresenter
    from tests.gui_fakes import new_home, cleanup_home
    from tests.test_gui_presenter import _fake_runtime

    home = new_home()
    d = _tmp_dir()
    p = _png_path(d)
    try:
        rt = _fake_runtime()
        presenter = GuiPresenter(rt, UiBridge())
        win = MainWindow(presenter, presenter.bridge)

        captured: dict = {}

        def fake_start(tid, text, **kw):
            captured[tid] = (text, kw)
            return "started"

        monkeypatch.setattr(presenter, "start_turn", fake_start)
        win._switch_to("t-img")
        win.image_strip.add_image(p)
        win.input_bar.edit.setPlainText("看图")
        win._on_input_submit("看图")

        text, kw = captured["t-img"]
        assert text == "看图"
        assert isinstance(kw.get("user_input"), list)
        assert any(x.get("type") == "image_url" for x in kw["user_input"])
        assert "图片 #1 路径" in kw["user_input_fallback"]
        # 附件条随发送清空
        assert win.image_strip.paths() == []
        # 用户气泡带缩略图行（第二块）
        pane = win.panes["t-img"]
        first = pane._vbox.itemAt(0).widget()
        second = pane._vbox.itemAt(1).widget()
        assert first is not None and "看图" in first.text()
        assert second is not None and second.widget() is not None  # 缩略图行（QScrollArea 包裹宿主）
    finally:
        cleanup_home(home)



# ---------------------------------------------------------------- #3：图片预览居中
def test_image_preview_centered_on_screen(qtbot):
    """#3：预览窗 show 前显式居中到当前屏 availableGeometry（不偏右/不出屏）。"""
    from src.gui.image_widgets import ImagePreview

    d = _tmp_dir()
    p = _png_path(d)
    prev = ImagePreview(p)
    qtbot.addWidget(prev)
    # 窗口被钉在（缩放后）pixmap 尺寸上
    assert prev.size() == prev.label.pixmap().size()
    # 位置 = availableGeometry 中心 − 窗口半尺寸（修复前为默认位置 (0,0)）
    from PySide6.QtCore import QPoint
    scr = prev.screen().availableGeometry()
    assert prev.pos() == scr.center() - QPoint(prev.width() // 2, prev.height() // 2)


def test_image_preview_missing_file_still_constructs(qtbot):
    """pixmap 加载失败（文件不存在）：不定尺寸、不居中，仍可构造不崩。"""
    from src.gui.image_widgets import ImagePreview

    prev = ImagePreview("nonexistent_dir_xyz/missing.png")
    qtbot.addWidget(prev)
    assert prev.label.pixmap().isNull()


def test_chip_rightclick_removes_leftclick_keeps(qtbot):
    """#5：右键缩略图=移除（与 ✕ 同路），左键=预览（不移除）。"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from src.gui.image_widgets import ImageStrip

    d = _tmp_dir()
    p = _png_path(d, "r.png")
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.add_image(p)
    chip = strip._chips[0]

    ev_right = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(1, 1),
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    chip.label.mousePressEvent(ev_right)
    assert strip.paths() == []            # 右键=移除

    strip.add_image(p)
    chip2 = strip._chips[0]
    ev_left = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(1, 1),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    chip2.label.mousePressEvent(ev_left)
    assert strip.paths() == [p]           # 左键=预览（弹 ImagePreview 无害），不移除
