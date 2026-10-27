"""定时任务面板（工单 10）：schedules/*.json 增删=加删文件；启用开关写回 enabled；
热重载 = gate.reload（kernel reload_schedules）；未启用 scheduler 时面板只读提示。"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src import scheduler as _sched


def load_task_rows(schedules_dir) -> list[dict]:
    """读全部任务文件（含 disabled，面板可看可切；*.example 跳过；坏 JSON 记坏行）。"""
    from pathlib import Path

    rows: list[dict] = []
    d = Path(schedules_dir)
    if not d.exists():
        return rows
    for path in sorted(d.glob("*.json")):
        if ".example." in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "file": path.name,
                    "name": str(data.get("id", path.stem)),
                    "cron": str(data.get("cron", "")),
                    "enabled": bool(data.get("enabled", True)),
                    "save_path": str(data.get("save_path", "")),
                    "path": path,
                    "bad": False,
                }
            )
        except (json.JSONDecodeError, OSError):
            rows.append(
                {"file": path.name, "name": path.stem, "cron": "", "enabled": False,
                 "save_path": "", "path": path, "bad": True}
            )
    return rows


def set_task_enabled(path, enabled: bool) -> None:
    """写回 enabled 键（保留文件其余内容）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["enabled"] = bool(enabled)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class SchedulerPanel(QDialog):
    """定时任务面板：任务清单（启用开关写回 + 热重载）+ 单 scheduler 门控状态。"""

    def __init__(self, presenter, parent=None) -> None:
        super().__init__(parent)
        self.presenter = presenter
        self.setWindowTitle("定时任务（schedules/ 目录，增删 = 加删文件）")
        self.resize(560, 380)
        root = QVBoxLayout(self)

        cfg = presenter.runtime.config
        self._dir = cfg.schedules_dir
        self._rows = load_task_rows(self._dir)

        body = QVBoxLayout()
        self._row_widgets: list[QWidget] = []
        for row in self._rows:
            w = self._build_row(row)
            self._row_widgets.append(w)
            body.addWidget(w)
        if not self._rows:
            body.addWidget(QLabel("（暂无定时任务：在 schedules/ 目录加 JSON 文件即增任务）"))
        root.addLayout(body, stretch=1)

        note = QLabel(
            "门控状态: "
            + ("已启用（本进程 --scheduled）" if presenter.runtime.gate.enabled
               else "未启用（重启 app 加 --scheduled 才运行定时任务）")
        )
        note.setStyleSheet("color:#8a99a8; font-size:11px;")
        root.addWidget(note)

        bar = QHBoxLayout()
        self.btn_reload = QPushButton("热重载（reload-schedules）")
        self.btn_reload.clicked.connect(self._reload)
        bar.addStretch(1)
        bar.addWidget(self.btn_reload)
        root.addLayout(bar)

    def _build_row(self, row: dict) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        cb = QCheckBox()
        cb.setChecked(row["enabled"])
        if row.get("bad"):
            cb.setEnabled(False)
        else:
            cb.toggled.connect(lambda on: self._toggle(row, on))
        h.addWidget(cb)
        cron_txt = ""
        if row["cron"]:
            try:
                cron_txt = _sched.describe_cron(row["cron"])
            except Exception:  # noqa: BLE001
                cron_txt = row["cron"]
        label = QLabel(f"{row['name']}（{row['file']}）  {cron_txt}" + ("  [坏文件]" if row.get("bad") else ""))
        h.addWidget(label, stretch=1)
        self._row_widgets and None  # noqa（占位防未用告警）
        return w

    def _toggle(self, row: dict, on: bool) -> None:
        try:
            set_task_enabled(row["path"], on)
            self.presenter.bridge.notify.emit(
                f"定时任务 {row['name']} {'已启用' if on else '已停用'}（写回 {row['file']}）"
            )
        except Exception as exc:  # noqa: BLE001
            self.presenter.bridge.notify.emit(f"写回失败: {exc}")

    def _reload(self) -> None:
        text = self.presenter.runtime.gate.reload()
        self.presenter.bridge.notify.emit(text)
