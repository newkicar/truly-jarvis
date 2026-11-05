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

from PySide6.QtCore import Qt, QSize, QTimer
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

from src.gui import md_render, theme

RENDER_BATCH_MS = 150
_DETAIL_OUTPUT_CAP = 8000
_BUBBLE_H = 96  # 用户气泡内缩略图边长

class CapLabel(QLabel):
    """wordwrap QLabel：附加最小宽度钳制。

    默认 QLabel.minimumSizeHint() 的宽度 = 最长不可断行（长 markdown 行 / 长 token
    可达数千 px），经 inner 布局 → QScrollArea → 窗口后端传播，让窗口被内容突然
    撑宽（非最大化模式下用户实测）。钳制后文字在窗口宽度内换行，窗口宽度不再
    随内容；上限不影响实际可拉伸宽度（sizePolicy 不变）。
    （Qt 先例：LabelWordWrapWide —— wordwrap 标签入布局必须重写 minimumSizeHint。）"""

    def minimumSizeHint(self):  # noqa: N802
        base = super().minimumSizeHint()
        return QSize(min(base.width(), 48), base.height())


def _detail_html(args_text: str, output_text: str, err: bool, depth: int) -> str:
    """工具详情区（等宽 args + 完整输出；错误态染红；超长截断）。"""
    out = str(output_text or "")
    truncated = ""
    if len(out) > _DETAIL_OUTPUT_CAP:
        out = out[:_DETAIL_OUTPUT_CAP]
        truncated = f"<br><br>…（截断，共 {len(str(output_text))} 字符）"
    tok = theme.current_tokens()
    color = tok["negative"] if err else tok["muted"]
    pad = "&nbsp;" * depth * 2
    args_soft = md_render.soft_break(str(args_text), 80).replace("\n", "<>br")
    out_soft = md_render.soft_break(out, 80).replace("\n", "<>br")
    return (
        f'<span style="font-family:Consolas,\'Courier New\',monospace; font-size:12px; color:{color};">'
        f"{pad}<b>args</b><br>{args_soft}"
        f"<br><br><b>output</b><br>{out_soft}<br>{truncated}</span>"
    )


class ToolLineWidget(QFrame):
    """工具调用行：一行摘要 +「＋ 详情」展开钮（codex「+ Show details」对标）。

    详情区 = 完整 args + 完整输出（等宽；错误态染红），默认折叠。
    """

    def __init__(self, name, args_text: str, err: bool, output: str, depth: int = 0) -> None:
        super().__init__()
        mark = "✗" if err else "✓"
        out_preview = str(output or "")
        if len(out_preview) > 160:
            out_preview = out_preview[:160] + "…"
        out_preview = md_render.soft_break(out_preview, 48)
        args_soft = md_render.soft_break(str(args_text)[:120], 48)
        summary = f"{'  ' * depth}{mark} {name}({args_soft})"
        if out_preview:
            summary += f"  → {out_preview}"

        self._expanded = False
        self._detail_html = _detail_html(str(args_text), str(output or ""), err, depth)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self._summary = CapLabel(summary)
        self._summary.setFont(md_render.mono_font())
        self._summary.setWordWrap(True)
        self._summary.setObjectName("tool-line")
        self._summary.setProperty("err", "true" if err else "false")
        self._summary.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        self.btn_toggle = QPushButton("＋ 详情")
        self.btn_toggle.setFixedWidth(76)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setObjectName("tool-toggle")
        self.btn_toggle.clicked.connect(self.toggle)
        row.addWidget(self._summary, stretch=1)
        row.addWidget(self.btn_toggle)
        lay.addLayout(row)

        self._detail = CapLabel()
        self._detail.setObjectName("tool-detail")
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
        self.setObjectName("thinking-box")
        self._buf = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        header = QHBoxLayout()
        self.btn_toggle = QPushButton("思考 ∧")
        self.btn_toggle.setFixedWidth(64)
        self.btn_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle.setObjectName("thinking-toggle")
        self._expanded = True
        self.btn_toggle.clicked.connect(self.toggle)
        header.addStretch(1)
        header.addWidget(self.btn_toggle)
        lay.addLayout(header)
        self._body = CapLabel()
        self._body.setObjectName("thinking-body")
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
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
        # gui15 徽标：pane 瞬态——等待审批卡 / 停止标记（main_window._refresh_running_badge 消费）
        self.awaiting_card = False
        self.stopped = False
        self.render_strategy = "batch"
        self._ai_label: CapLabel | None = None
        self._ai_buf = ""
        self._dirty = False
        self._thinking_box: ThinkingBox | None = None
        self._back_btn: QPushButton | None = None
        self._snap_timer: QTimer | None = None

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
        self._back_btn.setObjectName("back-pill")
        self._back_btn.setFixedSize(34, 34)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setText("↓")
        self._back_btn.setToolTip("回到底部")
        self._back_btn.clicked.connect(self.snap_to_bottom)
        self._back_btn.setParent(self.viewport())
        self._back_btn.setVisible(False)
        self._reposition_pill()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

        # 空会话占位（首条内容出现即从布局移除；rebuild 为空时复原）
        self._placeholder: CapLabel | None = None
        self._add_placeholder()

    def minimumSizeHint(self):  # noqa: N802
        """面板最小宽度固定上限：内容随窗口换行，窗口宽度不随内容（补充 CapLabel 钳制）。"""
        return QSize(200, 120)

    def _make_placeholder(self) -> "CapLabel":
        ph = CapLabel(
            "新会话\n在下方输入框里输入消息开始对话（Enter 发送，Shift+Enter 换行）"
        )
        ph.setObjectName("pane-placeholder")
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setContentsMargins(0, 80, 0, 0)
        return ph

    def _add_placeholder(self) -> None:
        self._placeholder = self._make_placeholder()
        self._insert(self._placeholder)

    # ---- 块追加
    def _insert(self, w: QWidget) -> None:
        # 插到 spacer 之前（保持 spacer 永远在底部 stretch）
        self._vbox.insertWidget(self._vbox.count() - 1, w)

    def _hide_placeholder(self) -> None:
        """首条内容出现：占位**移出布局**（不留 item 0 空位干扰索引），置 None。"""
        ph = self._placeholder
        if ph is not None:
            self._vbox.removeWidget(ph)
            ph.setParent(None)
            self._placeholder = None

    def append_user(self, text: str, image_paths: list[str] | None = None) -> None:
        self._close_thinking()
        self._hide_placeholder()
        l = CapLabel(md_render.soft_break(f"[你] {text}", 80))
        l.setObjectName("bub-user")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
        l.setTextFormat(Qt.TextFormat.PlainText)
        self._insert(l)
        if image_paths:
            self._insert(self._image_row(image_paths))
        self._follow()

    def _image_row(self, paths: list[str]) -> QWidget:
        """用户气泡内缩略图行（≈96px 高，可点放大——ImagePreview）。

        多张时整行宽度不再撑宽 pane：外包无边框横向 QScrollArea（只出横向提手）。"""
        from src.gui.image_widgets import ImagePreview, _thumb_pixmap

        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(6)

        def _zoom(pp: str) -> None:
            prev = ImagePreview(pp)
            host._preview = prev  # noqa: SLF001 — 持引用：WA_DeleteOnClose 顶层窗，防包装器被 GC
            prev.show()

        for p in paths:
            lab = QLabel()
            lab.setPixmap(_thumb_pixmap(p, _BUBBLE_H))
            lab.setFixedSize(_BUBBLE_H, _BUBBLE_H)
            lab.setCursor(Qt.CursorShape.PointingHandCursor)
            lab.setToolTip("点击放大")
            path = p
            lab.mousePressEvent = lambda _e, pp=path: _zoom(pp)  # noqa: SLF001 — 点击放大（居中预览窗，host 持引用）
            row.addWidget(lab)
        row.addStretch(1)
        scroller = QScrollArea()
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setWidgetResizable(True)
        scroller.setWidget(host)
        scroller.setFixedHeight(_BUBBLE_H + 4)
        return scroller

    def append_fallback(self, text: str) -> None:
        if not text:
            return
        self._close_thinking()
        self._hide_placeholder()
        l = CapLabel(md_render.md_to_qt_html(text))
        l.setObjectName("bub-ai")
        l.setTextFormat(Qt.TextFormat.RichText)
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
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
        l = CapLabel(md_render.soft_break(f"{'  ' * depth}[{name}] {status}", 80))
        l.setObjectName("line-sub")
        l.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
        l.setWordWrap(True)
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
            self._ai_label = CapLabel()
            self._ai_label.setObjectName("bub-ai")
            self._ai_label.setTextFormat(Qt.TextFormat.RichText)
            self._ai_label.setTextInteractionFlags(Qt.TextInteractionFlags.TextSelectableByMouse)
            self._ai_label.setWordWrap(True)
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
        self.snap_to_bottom()  # 审批卡强制显形（单生产调用点）

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
        if not records and self._placeholder is None:
            self._add_placeholder()  # 重建为空（undo 撤到空白）→ 复原占位
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
        # 刚追加内容 → 布局未定型 → maximum 可能还是旧值（↓回底/审批卡竞态）：
        # 50ms 后再吸附一次；若仍在增长则续 arm；用户上翻（stick=False）立即终止。
        self._resnap_soon()

    def _resnap_soon(self) -> None:
        if self._snap_timer is None:
            self._snap_timer = QTimer(self)
            self._snap_timer.setSingleShot(True)
            self._snap_timer.setInterval(50)
            self._snap_timer.timeout.connect(self._deferred_snap)
        if not self._snap_timer.isActive():
            self._snap_timer.start()

    def _deferred_snap(self) -> None:
        sb = self.verticalScrollBar()
        if not self.stick:
            return  # 用户上翻 → 绝不覆盖其阅读位置
        if sb.maximum() > sb.value():
            sb.setValue(sb.maximum())
            self._resnap_soon()  # 布局仍在收敛 → 续 arm 至真正底部

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
