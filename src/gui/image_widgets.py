"""图片附件条 Qt 部件（工单 07）：ImageStrip（缩略图 chip 行）+ ImagePreview（无边框放大窗）。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_THUMB = 56  # 输入区缩略图边长
_BUBBLE = 96  # 消息气泡内缩略图高度


def center_on_screen(w: QWidget) -> None:
    """顶层窗在 show 前显式居中到当前屏 availableGeometry（按 widget 当前尺寸）。

    Windows/Qt 给新建 frameless 顶层窗的默认摆放位置偏右且可能超出屏幕
    （图片预览出屏 bug，#3）-> show 前显式 move()；尺寸基准 = w.size()。
    （Qt 惯例：QMessageBox 等即按 availableGeometry 居中。）"""
    scr = w.screen().availableGeometry() if w.screen() else None
    if scr is None:
        return
    w.move(scr.center() - QPoint(w.width() // 2, w.height() // 2))


def _thumb_pixmap(path: str, side: int) -> QPixmap:
    pm = QPixmap(path)
    if pm.isNull():
        pm = QPixmap(side, side)
        pm.fill(Qt.GlobalColor.gray)
    return pm.scaled(
        side,
        side,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _Chip(QFrame):
    """单个缩略图 chip（56 圆角 + ✕）；点图 → zoom_requested(path)。"""

    zoom_requested = Signal(str)
    remove_requested = Signal(str)  # 右键 chip 图 → 移除（#5；左键=预览语义不变）

    def __init__(self, path: str, side: int = _THUMB, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)
        self.label = QLabel(self)
        pm = _thumb_pixmap(path, side)
        self.label.setPixmap(pm)
        self.label.setFixedSize(side, side)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.setObjectName("image-thumb")

        def _click(_e=None) -> None:
            if _e is not None and _e.button() == Qt.MouseButton.RightButton:
                self.remove_requested.emit(path)
            else:
                self.zoom_requested.emit(path)

        self.label.mousePressEvent = _click  # noqa: SLF001 — 简化点击→放大
        lay.addWidget(self.label)
        self.btn_rm = QPushButton("✕")
        self.btn_rm.setObjectName("img-remove")
        self.btn_rm.setFixedHeight(16)
        self.btn_rm.setToolTip("移除图片")
        lay.addWidget(self.btn_rm)


class ImageStrip(QFrame):
    """输入框上方附件条：有附件才显示。add_image/remove/clear/paths。"""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._paths: list[str] = []
        self._chips: list[_Chip] = []
        self._preview: ImagePreview | None = None  # #3：最近一个预览窗（持引用）
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(4, 2, 4, 2)
        self._lay.setSpacing(6)
        self.setVisible(False)

    def add_image(self, path: str) -> None:
        if not path or path in self._paths:
            return
        self._paths.append(path)
        chip = _Chip(path, side=_THUMB)
        chip.zoom_requested.connect(self._zoom)
        chip.remove_requested.connect(self.remove_image)  # #5 右键缩略图=移除（与 ✕ 同路）
        chip.btn_rm.clicked.connect(lambda: self.remove_image(path))
        self._chips.append(chip)
        self._lay.addWidget(chip)
        self.setVisible(True)
        self.changed.emit()

    def remove_image(self, path: str) -> None:
        if path not in self._paths:
            return
        self._paths.remove(path)
        for c in self._chips:
            if c.path == path:
                c.setParent(None)
                c.deleteLater()
                self._chips.remove(c)
        if not self._paths:
            self.setVisible(False)
        self.changed.emit()

    def clear(self) -> None:
        for c in self._chips:
            c.setParent(None)
            c.deleteLater()
        self._chips.clear()
        self._paths.clear()
        self.setVisible(False)
        self.changed.emit()

    def paths(self) -> list[str]:
        return list(self._paths)

    def _zoom(self, path: str) -> None:
        self._preview = ImagePreview(path)  # 持引用：WA_DeleteOnClose 顶层窗，防包装器被 GC
        self._preview.show()

    @staticmethod
    def bubble_pixmap(path: str, height: int = _BUBBLE) -> QPixmap:
        return _thumb_pixmap(path, height)


class ImagePreview(QWidget):
    """无边框放大窗：等比 ≤80% 屏，Esc/点击关闭。"""

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        pm = QPixmap(path)
        scr = self.screen().availableGeometry() if self.screen() else None
        if scr is not None and not pm.isNull():
            maxw, maxh = int(scr.width() * 0.8), int(scr.height() * 0.8)
            pm = pm.scaled(
                QSize(maxw, maxh),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setPixmap(pm)
        self.label.setScaledContents(False)
        self.label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.label.mousePressEvent = lambda _e: self.close()  # noqa: SLF001
        lay.addWidget(self.label)

        # 居中（#3）：frameless 顶层窗默认摆放偏右且可能出屏 → 显式定尺寸 + 居中
        if not pm.isNull():
            self.setFixedSize(pm.size())
            center_on_screen(self)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter):
            self.close()
        else:
            super().keyPressEvent(e)


__all__ = ["ImageStrip", "ImagePreview", "center_on_screen", "_thumb_pixmap"]
