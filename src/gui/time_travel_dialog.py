"""时间旅行与上下文（工单 09）：快照/回放/分支/回滚 + 压缩（GUI 渲染入口）。

逻辑全走 commands.py 既有纯函数（零内核改）：
- 快照：手动 /snapshot 语义（git 快照仅项目目录，vault 不纳入）
- 回放/分支：边界点列表（input/fork/update，短 id + 人类可读标签，短 id 前缀匹配）
- 压缩：/compact 对应按钮 + 可选提示词（整表重写随检查点持久化）
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src import commands


class TimeTravelDialog(QDialog):
    """当前会话的时间旅行面板：回放点列表 + 快照 + 压缩。"""

    def __init__(self, presenter, tid: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"时间旅行 — {tid}")
        self.presenter = presenter
        self.tid = tid
        self.resize(560, 420)

        root = QVBoxLayout(self)

        # ---- 回放点（边界点：input/fork/update，短 id + 标签）
        root.addWidget(QLabel("<b>回放点（从旧到新；选点可回放或开分支）</b>"))
        self.checkpoint_list = QListWidget()
        self.checkpoint_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        root.addWidget(self.checkpoint_list, stretch=1)
        self._refresh_checkpoints()

        row1 = QHBoxLayout()
        self.btn_replay = QPushButton("回放此点（重跑）")
        self.btn_fork = QPushButton("从此点开分支")
        self.btn_replay.clicked.connect(self._replay)
        self.btn_fork.clicked.connect(self._fork)
        row1.addWidget(self.btn_replay)
        row1.addWidget(self.btn_fork)
        root.addLayout(row1)

        # ---- 快照（手动，git 仅项目目录）
        row2 = QHBoxLayout()
        self.btn_snapshot = QPushButton("手动快照")
        self.btn_snapshots = QPushButton("快照列表")
        self.btn_snapshot.clicked.connect(self._snapshot)
        self.btn_snapshots.clicked.connect(self._list_snapshots)
        row2.addWidget(self.btn_snapshot)
        row2.addWidget(self.btn_snapshots)
        root.addLayout(row2)

        # ---- 上下文压缩（可选提示词）
        root.addWidget(QLabel("上下文压缩（整表重写，随检查点持久化）:"))
        row3 = QHBoxLayout()
        self.guide_edit = QLineEdit()
        self.guide_edit.setPlaceholderText("可选：压缩倾向提示词（留空 = 默认）")
        self.btn_compact = QPushButton("压缩")
        self.btn_compact.clicked.connect(self._compact)
        row3.addWidget(self.guide_edit, stretch=1)
        row3.addWidget(self.btn_compact)
        root.addLayout(row3)

        root.addWidget(QLabel("提示：回放/回退后如需对齐会话状态，可再「回放此点」。"))

    # ---- 数据
    def _refresh_checkpoints(self) -> None:
        self.checkpoint_list.clear()
        agent = self.presenter.runtime.agent
        for i, s in enumerate(commands.boundary_checkpoints(agent, self.tid), 1):
            cid = (s.config or {}).get("configurable", {}).get("checkpoint_id", "")
            src = (s.metadata or {}).get("source", "?")
            label = commands.last_human_text(s.values or {}) if src == "input" else ""
            text = f"{i}. [{src}] {(label or '—')[:40]}  {commands.checkpoint_short_id(cid)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, cid)  # 显示短 id，操作用全 id
            self.checkpoint_list.addItem(item)

    def _selected_cid(self) -> str | None:
        item = self.checkpoint_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    # ---- 动作（全部走 presenter worker，不在 UI 线程阻塞）
    def _replay(self) -> None:
        cid = self._selected_cid()
        if not cid:
            self.presenter.bridge.notify.emit("请先选择一个回放点。")
            return
        self.presenter.start_replay(self.tid, cid)
        self.close()

    def _fork(self) -> None:
        cid = self._selected_cid()
        if not cid:
            self.presenter.bridge.notify.emit("请先选择一个回放点。")
            return
        self.presenter.run_fork(self.tid, cid)
        self.close()

    def _snapshot(self) -> None:
        agent = self.presenter.runtime.agent
        tid = self.tid

        def _run() -> str:
            return commands.snapshot(agent, tid)

        self.presenter.run_command(_run, tid)

    def _list_snapshots(self) -> None:
        text = commands.list_snapshots()
        self._show_text("文件快照", text)

    def _compact(self) -> None:
        agent = self.presenter.runtime.agent
        tid = self.tid
        guide = self.guide_edit.text().strip() or None

        def _run() -> str:
            return commands.compact(agent, tid, guide)

        self.presenter.run_command(_run, tid)

    def _show_text(self, title: str, text: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.exec()
