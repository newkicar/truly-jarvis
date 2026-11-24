"""压缩基线展示（ADR-0014 ①④）：压缩前 UI 展示记录快照落盘。

自动/手动压缩会截断检查点历史；回合前快照（replay.compact_probe）在压缩发生时
追加到 <project_root>/.jarvis/compact_baselines/<tid>.json，UI 用「基线 + 当前
live」合并重建聊天面板（main_window._merged_display_records）——压缩后切走再切回
历史不再空白（对标 codex：token 可压缩、记录仍在屏上）。

纯展示增强：文件缺失 / 损坏 / 非 list → load 返回 []，不炸主流程；/undo 与会话
删除时 clear（undo 是撤销压缩，不是压缩）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# tid 落盘前消毒（防路径穿越 / 非法字符；空格、/ 等 → _）
_TID_SAFE = re.compile(r"[^0-9A-Za-z_-]")


def baselines_dir(root) -> Path:
    """压缩基线存放目录：<project_root>/.jarvis/compact_baselines。"""
    return Path(root) / ".jarvis" / "compact_baselines"


def _path(root, tid) -> Path:
    return baselines_dir(root) / f"{_TID_SAFE.sub('_', str(tid))}.json"


def _dump_record(r) -> dict:
    tool = getattr(r, "tool", None)
    return {
        "kind": getattr(r, "kind", ""),
        "text": getattr(r, "text", ""),
        "tool": None
        if tool is None
        else {
            "name": getattr(tool, "name", ""),
            "args_text": getattr(tool, "args_text", ""),
            "error": bool(getattr(tool, "error", False)),
            "output": getattr(tool, "output", ""),
            "depth": getattr(tool, "depth", 0),
        },
    }


def save_baseline(root, tid, records) -> None:
    """写该会话展示记录快照（JSON 列表，整表覆盖；父目录自动创建）。"""
    p = _path(root, tid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([_dump_record(r) for r in records], ensure_ascii=False),
        encoding="utf-8",
    )


def load_baseline(root, tid) -> list:
    """读快照（replay.Record 序列）；缺失 / 损坏 / 非 list → []。"""
    from src.gui import replay

    p = _path(root, tid)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list = []
    for item in data:
        if not isinstance(item, dict):
            continue
        t = item.get("tool")
        tool = None
        if isinstance(t, dict):
            tool = replay.ToolRecord(
                t.get("name", ""),
                t.get("args_text", ""),
                bool(t.get("error", False)),
                t.get("output", ""),
                int(t.get("depth", 0) or 0),
            )
        out.append(
            replay.Record(str(item.get("kind", "")), str(item.get("text", "")), tool)
        )
    return out


def clear_baseline(root, tid) -> None:
    """删该会话压缩基线（会话删除 / undo 到空白时调用；不存在则 no-op）。"""
    _path(root, tid).unlink(missing_ok=True)
