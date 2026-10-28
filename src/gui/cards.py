"""HITL 内联审批卡片（工单 04）：codex 式卡片 + 表单 + diff 三件套。

- 卡片出现在聊天流（pane.append_card），不遮挡历史；非模态。
- 四按钮：放行（主按钮、卡片打开即默认焦点）/ 永久放行（execute 前缀可编辑）/
  拒绝 / 编辑参数（卡片内展开表单：原值只读展示行 + 编辑框，留空=保留原值，
  「看得见改」平移 TUI EditParamsModal 语义）+「放弃本轮」显式标注（放弃≠取消任务）。
- worker 侧：make_card_ask 的 CardSession threading.Event 阻塞等决策，
  结果 dict 与 TUI/CLI 同构（{"decision": ...}），resume 契约零内核改。
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.gui import md_render


class CardSession:
    """worker 侧阻塞句柄：event 置位后 result = 决策 dict 或 None（放弃本轮）。"""

    __slots__ = ("event", "result")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.result: dict | None = None


def _clip(v: Any, n: int) -> str:
    s = str(v)
    return s if len(s) <= n else s[:n] + "…"


def _soft_break(text: str, every: int = 60) -> str:
    """长无空格 token 每 every 字符强制断行。

    PySide6 6.12 的 QLabel 未暴露 WordWrapMode.BreakWord：不换行长 token 会把
    QLabel minimumSizeHint 顶到数千 px（600 字 ≈ 7200px 实证）→ 卡片最小宽把
    会话面板/主窗口撑出屏幕（2026-10-28 报障「审批栏太宽超出界面」）。
    显式 \\n 断行后 wordWrap 生效、最小宽塌缩到按钮行。
    """
    out: list[str] = []
    for seg in str(text).split("\n"):
        while len(seg) > every:
            out.append(seg[:every])
            seg = seg[every:]
        out.append(seg)
    return "\n".join(out)


class ApprovalCard(QFrame):
    """codex 式内联审批卡片。on_decision(result)/on_abandon() 由 owner 注入。"""

    def __init__(
        self,
        inv: Any,
        preview: str,
        on_decision: Callable[[dict], None],
        on_abandon: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_decision = on_decision
        self._on_abandon = on_abandon
        self._locked = False
        self._inv = inv
        self._editor_shown = False
        self._card_id = uuid.uuid4().hex[:8]

        self.setObjectName("approval_card")
        self.setStyleSheet(
            "#approval_card { border:1px solid #7a5c00; border-radius:6px; background:#2a2517; }"
        )
        # 卡片宽度随面板收缩（内容用 _soft_break 断行，不再顶出窗口）
        self.setMinimumWidth(0)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)

        head = QLabel(f"<b>需要审批 · {inv.name}</b>")
        head.setStyleSheet("color:#ffd75e; font-size:14px;")
        head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(head)

        if getattr(inv, "path", None):
            p = QLabel(f"目标: {_soft_break(str(inv.path), 48)}")
            p.setStyleSheet("color:#bbbbbb;")
            p.setWordWrap(True)
            p.setMinimumWidth(0)
            outer.addWidget(p)

        if preview:
            # 固定高只读编辑框：最小宽塌缩（QLabel 即使断行仍被最长行顶宽），
            # 长 diff 内部滚动；mono 字体 + 可选鼠标选中
            pv = QPlainTextEdit(_soft_break(preview, 48))
            pv.setReadOnly(True)
            pv.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            pv.setFont(md_render.mono_font())
            pv.setFixedHeight(120)
            pv.setStyleSheet(
                "QPlainTextEdit { color:#c8c8c8; background:#1c1c1c; border-radius:4px; padding:4px; }"
            )
            outer.addWidget(pv)

        note = QLabel("「放弃本轮」= 放弃本轮（工具不会执行；不是取消整个任务）")
        note.setStyleSheet("color:#888888; font-size:11px;")
        outer.addWidget(note)

        btns1 = QHBoxLayout()
        self.btn_approve = QPushButton("放行")
        self.btn_always = QPushButton("永久放行")
        self.btn_reject = QPushButton("拒绝")
        self.btn_edit = QPushButton("编辑参数")
        self.btn_giveup = QPushButton("放弃本轮")
        self.btn_approve.setStyleSheet(
            "QPushButton { background:#2e7d32; color:white; font-weight:bold;"
            " border-radius:4px; padding:4px 10px; }"
        )
        self.btn_reject.setStyleSheet(
            "QPushButton { background:#8e2020; color:white; border-radius:4px; padding:4px 10px; }"
        )
        # 两行按钮（旧 5 按钮单行最小宽 ~820px 会把面板顶出窄窗口）：
        # 行 1 = 主操作（放行/永久放行/拒绝），行 2 = 次操作（编辑参数/放弃本轮）
        for b in (self.btn_approve, self.btn_always, self.btn_reject):
            b.setMinimumWidth(0)
            btns1.addWidget(b)
        btns2 = QHBoxLayout()
        for b in (self.btn_edit, self.btn_giveup):
            b.setMinimumWidth(0)
            btns2.addWidget(b)
        btns2.addStretch(1)
        outer.addLayout(btns1)
        outer.addLayout(btns2)
        outer.addWidget(self._editor_slot())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.btn_approve.setFocus()  # 卡片打开即默认焦点（单次 Enter 完成审批）

        self.btn_approve.clicked.connect(lambda: self._decide({"decision": "approve"}))
        self.btn_always.clicked.connect(self._on_always_clicked)
        self.btn_reject.clicked.connect(lambda: self._decide({"decision": "reject"}))
        self.btn_giveup.clicked.connect(self._abandon)
        self.btn_edit.clicked.connect(self._open_editor)
        self.btn_edit.setEnabled(inv.name in ("execute", "write_file", "edit_file"))

    # ---- 永久放行（execute 走前缀编辑；文件工具整工具放行）
    def _on_always_clicked(self) -> None:
        inv = self._inv
        if inv.name == "execute":
            from src.permissions import extract_command_prefix

            cmd = str((inv.args or {}).get("command", ""))
            default_prefix = extract_command_prefix(cmd)
            row = QHBoxLayout()
            lab = QLabel(f"前缀（默认 {default_prefix}）:")
            lab.setStyleSheet("color:#bbbbbb;")
            self._prefix_edit = QLineEdit(default_prefix)
            self._prefix_edit.setFixedWidth(240)
            self._prefix_edit.setFont(md_render.mono_font())
            ok = QPushButton("确认永久放行")
            ok.clicked.connect(
                lambda: self._decide(
                    {"decision": "always_approve", "prefix": self._prefix_edit.text().strip() or default_prefix}
                )
            )
            row.addWidget(lab)
            row.addWidget(self._prefix_edit)
            row.addWidget(ok)
            host = QFrame()
            host.setLayout(row)
            self.layout().insertWidget(self.layout().count() - 1, host)
            host.show()
        else:
            self._decide({"decision": "always_approve"})

    # ---- 编辑参数表单（留空=保留原值；execute 单行 / write·edit 多行）
    def _editor_slot(self) -> QFrame:
        slot = QFrame()
        slot.setVisible(False)
        self._editor_box = slot
        return slot

    def _open_editor(self) -> None:
        if self._editor_shown or self._locked:
            return
        self._editor_shown = True
        inv = self._inv
        args = dict(inv.args or {})
        box = self._editor_box
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 4, 0, 4)
        label = QLabel("编辑参数（留空 = 保留原值）:")
        label.setStyleSheet("color:#bbbbbb;")
        bl.addWidget(label)
        single_line = inv.name == "execute"
        editors: list[tuple[str, "QLineEdit | QPlainTextEdit"]] = []
        for k, v in args.items():
            kl = QLabel(f"<b>{k}</b>（原值）")
            kl.setStyleSheet("color:#999999;")
            kl.setTextFormat(Qt.TextFormat.RichText)
            bl.addWidget(kl)
            orig = QPlainTextEdit(_soft_break(_clip(v, 400), 48))
            orig.setReadOnly(True)
            orig.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            orig.setFont(md_render.mono_font())
            orig.setFixedHeight(60)
            orig.setStyleSheet("QPlainTextEdit { color:#6a727c; background:#181c22; }")
            bl.addWidget(orig)
            if single_line:
                ed: QLineEdit | QPlainTextEdit = QLineEdit(str(v or ""))
            else:
                ed = QPlainTextEdit(str(v or ""))
                ed.setFixedHeight(90)
            ed.setFont(md_render.mono_font())
            bl.addWidget(ed)
            editors.append((k, ed))
        ok = QPushButton("确认编辑后放行")
        ok.setStyleSheet(
            "QPushButton { background:#1565c0; color:white; border-radius:4px; padding:4px 10px; }"
        )
        bl.addWidget(ok)

        def _confirm() -> None:
            edited = dict(args)
            for k, e in editors:
                nv = e.text() if isinstance(e, QLineEdit) else e.toPlainText()
                if nv:  # 留空 = 保留原值（不 strip，保多行）
                    edited[k] = nv
            self._decide({"decision": "edit", "edited": edited})

        ok.clicked.connect(_confirm)
        box.show()

    # ---- 决策 / 放弃
    def _decide(self, result: dict) -> None:
        if self._locked:
            return
        self._locked = True
        self._lock_buttons()
        text = {
            "approve": "已放行",
            "always_approve": "已永久放行（写入 jarvis.json）",
            "reject": "已拒绝",
            "edit": "已编辑参数并放行",
        }.get(str(result.get("decision")), "?")
        head = QLabel(f"<b>✓ {text}</b>")
        head.setStyleSheet("color:#6fd66f;")
        head.setTextFormat(Qt.TextFormat.RichText)
        self.layout().addWidget(head)
        self._on_decision(result)

    def _abandon(self) -> None:
        if self._locked:
            return
        self._locked = True
        self._lock_buttons()
        head = QLabel("<b>已放弃本轮（工具未执行）</b>")
        head.setStyleSheet("color:#e57373;")
        head.setTextFormat(Qt.TextFormat.RichText)
        self.layout().addWidget(head)
        self._on_abandon()

    def _lock_buttons(self) -> None:
        for b in (self.btn_approve, self.btn_always, self.btn_reject, self.btn_edit, self.btn_giveup):
            b.setEnabled(False)


# ---------------------------------------------------------------- owner 侧装配


def make_card_ask(runtime, bridge) -> Callable[[Any, str], dict | None]:
    """presenter 的 ask_action 实现：create_card 信号把卡片挂到对应 pane，
    worker 阻塞等 CardSession；返回决策 dict 或 None（放弃本轮）。"""
    from src.tui_format import permission_preview

    cards: dict[str, CardSession] = {}

    def ask(inv: Any, tid: str) -> dict | None:
        preview = permission_preview(
            inv,
            vault_path=runtime.config.vault_path,
            workspace_root=runtime.config.project_root,
        )
        cs = CardSession()
        card_id = uuid.uuid4().hex
        cards[card_id] = cs
        bridge.notify.emit(f"等待审批 {inv.name}…")

        def on_decision(result: dict) -> None:
            cs.result = result
            bridge.focus_input.emit()
            cs.event.set()

        def on_abandon() -> None:
            cs.result = None
            bridge.focus_input.emit()
            cs.event.set()

        payload = (inv, preview, card_id, on_decision, on_abandon)
        bridge.create_card.emit(tid, payload, card_id)
        cs.event.wait()
        cards.pop(card_id, None)
        return cs.result

    return ask


def card_widget_from_payload(payload) -> ApprovalCard:
    """UiBridge.create_card 载荷 → ApprovalCard（主线程构造入 pane）。"""
    inv, preview, _card_id, on_decision, on_abandon = payload
    return ApprovalCard(inv, preview, on_decision, on_abandon)
