"""每 thread 独立消息栈聊天面板（QScrollArea + 粘底跟随状态机）。

切会话 = 换栈不重建 runtime（每个 thread 一个 ChatPane 实例常驻 QStackedWidget）。
工单 03 过稿形状：
- 粘底状态机（stick）：贴底=跟随，上翻=停跟随；悬浮「↓」小圆钮（贴聊天区右下角、
  不占布局行）上翻显/到底隐，点击=跳底恢复跟随（tui-ux16r2 平移）。
- 流式 Markdown 合批重渲（150ms，owner 的 QTimer 驱动 flush_dirty）；逐 token 即时
  策略开关 render_strategy="instant"。
- PgUp/PgDn/Home/End 四键 + 点击聚焦（工单 03/06 联动 stick）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui import md_render

RENDER_BATCH_MS = 150
_DETAIL_OUTPUT_CAP = 8000
_BUBBLE_H = 96  # 用户气泡内缩略图边长


def _detail_html(args_text: str, output_text: str, err: bool, depth: int) -> str:
    """工具详情区（等宽 args + 完整输出；错误态染红；超长截断）。"""
    out = str(output_text or "")
    truncated = ""
    if len(out) > _DETAIL_OUTPUT_CAP:
        out = out[:_DETAIL_OUTPUT_CAP]
        truncated = f"<br><br>…（截断，共 {len(str(output_text))} 字符）"
    color = "#e57373" if err else "#c8c8c8"
    pad = "&nbsp;" * depth * 2
    return (
        f'<span style="font-family:Consolas,\'Courier New\',monospace; font-size:12px; color:{color};">'
        f"{pad}<b>args</b><br>{args_text.replace(chr(10), '<br>')}"
        f"<br><br><b>output</b><br>{out.replace(chr(10), '<br>')}<br>{truncated}</span>"
    )


class ToolLineWidget(QFrame):
    """工具调用行：一行摘要 +「＋ 详情」展开钮（codex「+ Show details」对标）。

    详情区 = 完整 args + 完整输出（等宽；错误态染红），默认折叠。
    """

    def __init__(self, name, args_text: str, err: bool, output: str, depth: int = 0) -> None:
        super().__init__()
        mark = "✗" if err else "✓"
        color = "#e57373" if err else "#7fbf7f"
        out_preview = str(output or "")
        if len(out_preview) > 160:
            out_preview = out_preview[:160] + "…"
        summary = f"{'  ' * depth}{mark} {name}({str(args_text)[:120]})"
        if out_preview:
            summary += f"  → {out_preview}"

        self._expanded = False
        self._detail_html = _detail_html(str(args_text), str(output or ""), err, depth)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._summary = QLabel(summary)
        self._summary.setFont(md_render.mono_font())
        self._summary.setStyleSheet(f"color:{color}; font-size:12px;")
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        self.btn_toggle = QPushButton("＋ 详情")
        self.btn_toggle.setFixedWidth(76)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet(
            "QPushButton { color:#8ab4f8; background:transparent; border:1px solid #334155;"
            " border-radius:4px; font-size:11px; }"
        )
        self.btn_toggle.clicked.connect(self.toggle)
        row.addWidget(self._summary, stretch=1)
        row.addWidget(self.btn_toggle)
        lay.addLayout(row)

        self._detail = QLabel()
        self._detail.setTextFormat(Qt.TextFormat.RichText)
        self._detail.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        self._detail.setWordWrap(True)
        self._detail.setVisible(False)
        lay.addWidget(self._detail)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        if self._expanded:
            self._detail.setText(self._detail_html)
        self.btn_toggle.setText("－ 收起" if self._expanded else "＋ 详情")


class ThinkingBox(QFrame):
    """思考块（工单 06）：小字淡色、回答上方、默认展开可折叠。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._buf = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        header = QHBoxLayout()
        self.btn_toggle = QPushButton("思考 ∧")
        self.btn_toggle.setFixedWidth(64)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setStyleSheet(
            "QPushButton { color:#8a99a8; background:transparent; border:none;"
            " font-size:11px; }"
        )
        self._expanded = True
        self.btn_toggle.clicked.connect(self.toggle)
        header.addStretch(1)
        header.addWidget(self.btn_toggle)
        lay.addLayout(header)
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        self._body.setStyleSheet("color:#8a99a8; font-size:11px;")
        lay.addWidget(self._body)

    def add_delta(self, t: str) -> None:
        self._buf += t
        self._body.setText(self._buf)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self.btn_toggle.setText("思考 ∧" if self._expanded else "思考 ∨")



class ChatPane(QScrollArea):
    """单个会话的消息面板。owner 负责流事件 → append_* 的映射。"""

    def __init__(self, tid: str, parent=None) -> None:
        super().__init__(parent)
        self.tid = tid
        self.stick = True
        self.running = False
        self.render_strategy = "batch"
        self._ai_label: QLabel | None = None
        self._ai_buf = ""
        self._dirty = False
        self._thinking_box: ThinkingBox | None = None
        self._back_btn: QPushButton | None = None

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 点击聚焦（四键前提）
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self._vbox = QVBoxLayout(inner)
        self._vbox.setContentsMargins(10, 10, 10, 10)
        self._vbox.setSpacing(6)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vbox.addWidget(spacer, stretch=1)
        self.setWidget(inner)

        # 悬浮「↓」pill：viewport 子部件（滚动不带走），贴右下角、不占布局行
        self._back_btn = QPushButton("↓")
        self._back_btn.setFixedSize(34, 34)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setText("↓")
        self._back_btn.setToolTip("回到底部")
        self._back_btn.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border-radius:17px;"
            " font-size:16px; font-weight:bold; } QPushButton:hover { background:#1976d2; }"
        )
        self._back_btn.clicked.connect(self.snap_to_bottom)
        self._back_btn.setParent(self.viewport())
        self._back_btn.setVisible(False)
        self._reposition_pill()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 空会话占位（首条 user/AI/工具内容出现即隐藏；回放/undo 重建后若空则复现）
        self._placeholder = QLabel(
            "新会话\n在下方输入框里输入消息开始对话（Enter 发送，Shift+Enter 换行）"
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color:#5c6773; font-size:13px;")
        self._placeholder.setContentsMargins(0, 80, 0, 0)
        self._insert(self._placeholder)

    # ---- 块追加
    def _insert(self, w: QWidget) -> None:
        # 插到 spacer 之前（保持 spacer 永远在底部 stretch）
        self._vbox.insertWidget(self._vbox.count() - 1, w)

    def _hide_placeholder(self) -> None:
        ph = getattr(self, "_placeholder", None)
        if ph is not None and not ph.isHidden():  # isHidden（isVisible 在未 show 时恒 False）
            ph.hide()

    def append_user(self, text: str, image_paths: list[str] | None = None) -> None:
        self._close_thinking()
        self._hide_placeholder()
        l = QLabel(f"[你] {text}")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setTextFormat(Qt.TextFormat.PlainText)
        l.setStyleSheet("color:#e8e8e8; background:#1f3a5f; border-radius:4px; padding:6px;")
        self._insert(l)
        if image_paths:
            self._insert(self._image_row(image_paths))
        self._follow()

    def _image_row(self, paths: list[str]) -> QWidget:
        """用户气泡内缩略图行（≈96px 高，可点放大——ImagePreview）。"""
        from src.gui.image_widgets import ImagePreview, _thumb_pixmap

        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(6)
        for p in paths:
            lab = QLabel()
            lab.setPixmap(_thumb_pixmap(p, _BUBBLE_H))
            lab.setFixedSize(_BUBBLE_H, _BUBBLE_H)
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.setToolTip("点击放大")
            path = p
            lab.mousePressEvent = lambda _e, pp=path: ImagePreview(pp).show()  # noqa: SLF001
            row.addWidget(lab)
        row.addStretch(1)
        return host

    def append_fallback(self, text: str) -> None:
        if not text:
            return
        self._close_thinking()
        self._hide_placeholder()
        l = QLabel(md_render.md_to_qt_html(text))
        l.setTextFormat(Qt.TextFormat.RichText)
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setStyleSheet("background:#101820; border-radius:4px; padding:6px;")
        self._insert(l)
        self._follow()

    def append_tool(self, name, args, err, output, depth=0) -> None:
        """工具行 = 一行摘要 +「＋ 详情」展开钮（默认折叠，工单 06）。"""
        self._close_thinking()
        self._hide_placeholder()
        w = ToolLineWidget(str(name), str(args), bool(err), str(output or ""), depth)
        self._insert(w)
        self._follow()

    def append_subagent(self, name, status, depth=0) -> None:
        self._hide_placeholder()
        l = QLabel(f"{'  ' * depth}[{name}] {status}")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setStyleSheet("color:#ffd75e; font-size:12px;")
        self._insert(l)
        self._follow()

    # ---- 思考块（工单 06；小字淡色，回答上方，默认展开可折叠）
    def thinking_delta(self, delta: str) -> None:
        if self._thinking_box is None:
            self._thinking_box = ThinkingBox()
            self._insert(self._thinking_box)
        self._thinking_box.add_delta(delta)
        self._follow()

    def _close_thinking(self) -> None:
        # 块保留在 pane（可折叠），后续思考再起新块
        self._thinking_box = None

    # ---- 流式 AI 消息（合批 / 即时双策略）
    def ai_delta(self, delta: str) -> None:
        self._ai_buf += delta
        if self._ai_label is None:
            self._ai_label = QLabel()
            self._ai_label.setTextFormat(Qt.TextFormat.RichText)
            self._ai_label.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
            self._ai_label.setWordWrap(True)
            self._ai_label.setStyleSheet("background:#101820; border-radius:4px; padding:6px;")
            self._hide_placeholder()
            self._insert(self._ai_label)
        if self.render_strategy == "instant":
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf))
            self._dirty = False
            self._follow()
        else:
            self._dirty = True  # 150ms 合批由 owner 的 QTimer 驱动 flush_dirty

    def flush_dirty(self) -> None:
        """合批渲染：owner 的 RENDER_BATCH_MS 定时器调用。"""
        if self._dirty and self._ai_label is not None:
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf))
            self._dirty = False
            self._follow()

    def ai_end(self, text: str) -> None:
        self._close_thinking()
        if self._ai_label is not None:
            self._ai_label.setText(md_render.md_to_qt_html(self._ai_buf or text))
            self._ai_label = None
            self._ai_buf = ""
            self._dirty = False
        elif text:
            self.append_fallback(text)
        self._follow()

    def append_card(self, card: QWidget) -> None:
        self._hide_placeholder()
        self._insert(card)
        self._follow()

    def rebuild_from_records(self, records: list) -> None:
        """工单 06：从检查点记录重建（user/AI 文本 + 工具行，工具行默认折叠）。"""
        for r in records:
            if r.kind == "user":
                self.append_user(r.text)
            elif r.kind == "ai":
                self.append_fallback(r.text)
            elif r.kind == "tool" and r.tool is not None:
                t = r.tool
                self.append_tool(t.name, t.args_text, t.error, t.output, t.depth)
        self.stick = True
        self.snap_to_bottom()

    # ---- 粘底状态机
    def _at_bottom(self, tol: int = 4) -> bool:
        sb = self.verticalScrollBar()
        return sb.value() >= sb.maximum() - tol

    def _follow(self) -> None:
        if self.stick:
            self.snap_to_bottom()

    def snap_to_bottom(self) -> None:
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())
        self.stick = True
        self._set_pill(False)

    def _on_scroll(self, _v: int) -> None:
        bottom = self._at_bottom()
        self.stick = bottom
        self._set_pill(not bottom)

    def _set_pill(self, visible: bool) -> None:
        if self._back_btn is not None:
            self._back_btn.setVisible(visible)

    def _reposition_pill(self) -> None:
        if self._back_btn is None:
            return
        vp = self.viewport()
        self._back_btn.move(vp.width() - 44, vp.height() - 44)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._reposition_pill()

    # ---- 四键滚动 + 点击聚焦（工单 03）
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        sb = self.verticalScrollBar()
        page = max(1, self.viewport().height())
        if event.key() == Qt.Key_PageUp:
            sb.setValue(sb.value() - page)
            self._on_scroll(sb.value())
            return
        if event.key() == Qt.Key_PageDown:
            sb.setValue(sb.value() + page)
            self._on_scroll(sb.value())
            return
        if event.key() == Qt.Key_Home:
            sb.setValue(0)
            self._on_scroll(0)
            return
        if event.key() == Qt.Key_End:
            self.snap_to_bottom()
            return
        super().keyPressEvent(event)
