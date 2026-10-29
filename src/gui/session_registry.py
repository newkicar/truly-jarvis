"""会话注册表 + AI 命名（工单 05，纯逻辑可单测）。

sessions.json（项目级，gitignore；schema）::

    { "<thread_id>": { "title": "修复登录 401", "ai_generated": true } }

- 标签解析：注册表短名 > 首条用户消息截 18 字（commands.session_label）> thread_id。
- AI 命名：首轮 finalize 后后台生成（generate_session_name，用 agent._jarvis_model
  小 prompt）；失败/超时静默回落摘要名，不崩。
- 可删：注册表缺失/损坏 = 全回落摘要，不崩。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src import commands


def registry_path(project_root: Path) -> Path:
    return Path(project_root) / "sessions.json"


class SessionRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self, tid: str) -> dict | None:
        entry = self.load().get(tid)
        return entry if isinstance(entry, dict) else None

    def rename(self, tid: str, title: str, *, ai_generated: bool = False) -> None:
        data = self.load()
        entry = data.get(tid)
        entry = dict(entry) if isinstance(entry, dict) else {}
        entry["title"] = title
        entry["ai_generated"] = ai_generated
        data[tid] = entry
        self._atomic_write(data)

    def _set_flag(self, tid: str, key: str, value: bool) -> None:
        data = self.load()
        entry = data.get(tid)
        entry = dict(entry) if isinstance(entry, dict) else {}
        entry[key] = value
        data[tid] = entry
        self._atomic_write(data)

    def set_pinned(self, tid: str, on: bool) -> None:
        self._set_flag(tid, "pinned", on)

    def set_archived(self, tid: str, on: bool) -> None:
        self._set_flag(tid, "archived", on)

    def is_pinned(self, tid: str) -> bool:
        return bool((self.get(tid) or {}).get("pinned", False))

    def is_archived(self, tid: str) -> bool:
        return bool((self.get(tid) or {}).get("archived", False))

    def delete(self, tid: str) -> None:
        data = self.load()
        if data.pop(tid, None) is not None:
            self._atomic_write(data)

    def label(self, agent: Any, tid: str) -> str:
        entry = self.get(tid)
        if entry and str(entry.get("title", "")).strip():
            return str(entry["title"]).strip()
        return commands.session_label(agent, tid)

    def _atomic_write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


# ---------------------------------------------------------------- AI 命名（纯函数）


def session_naming_prompt(user_text: str) -> str:
    return (
        "把下面这段「用户与 AI 助手对话」总结成一个不超过 12 字的会话短名（名词短语，"
        "不加标点、不加引号、不要换行，直接输出短名本身）：\n"
        f"{user_text[:600]}"
    )


def clean_name_reply(raw: str) -> str | None:
    """模型回复 → 短名：取首行、剥引号/书名号、截 16 字；空 = None（回落摘要名）。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    lines = s.splitlines()
    if not lines:
        return None
    line = lines[0].strip()
    for ch in ("“", "”", '"', "'", "「", "」", "《", "》", "*", "`"):
        line = line.strip(ch)
    line = line.strip()
    if not line:
        return None
    return line[:16]


def generate_session_name(model: Any, user_text: str) -> str | None:
    """后台命名：小 prompt 单次调用；异常/空 → None（静默回落，不崩）。"""
    if model is None:
        return None
    try:
        reply = model.invoke(session_naming_prompt(user_text))
    except Exception:  # noqa: BLE001 — 命名是增强，绝不阻塞/炸主流程
        return None
    text = getattr(reply, "content", None)
    if isinstance(text, list):  # 多模态 content 块
        text = "".join(str(b.get("text", "")) for b in text if isinstance(b, dict))
    return clean_name_reply(str(text or ""))
