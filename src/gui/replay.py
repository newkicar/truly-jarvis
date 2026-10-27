"""会话回放记录重建（工单 06：工具行持久化，切会话/重启 app 不丢）。

从检查点消息重建 user/AI 文本 + 工具行（AIMessage.tool_calls × ToolMessage
按 tool_call_id 配对；输出/错误态齐全；工具行默认折叠带「＋ 详情」）。
只读 get_state，不改检查点写入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src import commands


@dataclass
class ToolRecord:
    name: str
    args_text: str
    error: bool
    output: str
    depth: int = 0


@dataclass
class Record:
    kind: str  # user / ai / tool
    text: str = ""
    tool: ToolRecord | None = None


def _msg_text(m: Any) -> str:
    c = getattr(m, "content", "")
    if isinstance(c, str):
        return c
    if isinstance(c, list):  # 多模态 content 块
        parts = []
        for b in c:
            if isinstance(b, dict) and b.get("type") in ("text", None):
                parts.append(str(b.get("text", "")))
            elif isinstance(b, str):
                parts.append(b)
        return "\n".join(p for p in parts if p)
    return str(c)


def thread_record(agent: Any, thread_id: str, max_messages: int = 500) -> list[Record]:
    """检查点消息 → 展示记录序列（user/AI 文本 + 工具行，tool_call_id 配对）。"""
    import json

    state = agent.get_state(commands.thread_config(thread_id))
    messages = ((state.values or {}).get("messages")) or [] if state else []
    if len(messages) > max_messages:
        messages = messages[-max_messages:]

    pending: dict[str, tuple[str, str]] = {}  # call_id → (name, args_text)
    records: list[Record] = []

    for m in messages:
        mtype = getattr(m, "type", "")
        if mtype == "human":
            t = _msg_text(m)
            if t:
                records.append(Record("user", t))
        elif mtype == "ai":
            t = _msg_text(m)
            if t:
                records.append(Record("ai", t))
            for tc in getattr(m, "tool_calls", None) or []:
                name = tc.get("name", "?") if isinstance(tc, dict) else getattr(tc, "name", "?")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                cid = (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", "")) or ""
                try:
                    args_text = json.dumps(args, ensure_ascii=False)
                except (TypeError, ValueError):
                    args_text = str(args)
                if cid:
                    pending[cid] = (name, args_text)
                else:  # 无 id 的 tool_call（历史脏数据）：立即出一行
                    records.append(Record("tool", "", ToolRecord(name, args_text, False, "")))
        elif mtype == "tool":
            cid = getattr(m, "tool_call_id", "") or ""
            name, args_text = pending.pop(cid, ("?", ""))
            err = getattr(m, "status", None) == "error" or _looks_like_error(_msg_text(m))
            records.append(
                Record("tool", "", ToolRecord(name, args_text, err, _msg_text(m)))
            )
        # system / 其他 → 不展示
    # 悬挂 tool_call（中断轮 / 未回填结果）→ 也出一行（默认折叠，无输出）
    for name, args_text in pending.values():
        records.append(Record("tool", "", ToolRecord(name, args_text, False, "")))
    return records


def _looks_like_error(text: str) -> bool:
    t = (text or "")[:200]
    return t.startswith("[ERROR]") or t.startswith("[Command failed")
