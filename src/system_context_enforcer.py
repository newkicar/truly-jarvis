"""系统上下文强制层（ADR-0003）。

对简单的日期/时间/位置事实问句，在 before_model 直接 short-circuit，
避免模型用训练记忆或 CodeInterpreter 乱答；时间与城市走本机 shell（与 execute 等价）。
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.permissions import _tool_arg_value

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")

_COMPLEX_MARKERS = (
    "调研",
    "报告",
    "整理",
    "搜索",
    "检索",
    "vault",
    "笔记",
    "inbox",
    "保存",
    "执行",
    "运行",
    "代码",
    "脚本",
    "fan-out",
    "写进",
    "写入",
)
_SCHEDULE_MARKERS = ("开会", "会议", "提醒", "定时", "约", "schedule")

_DATE_PATTERNS = (
    re.compile(r"(今天|今日).{0,10}(几号|日期|星期几|周几|哪天)"),
    re.compile(r"^(今天)?(是)?几月几号"),
    re.compile(r"(星期几|周几|什么日子)"),
    re.compile(r"today.{0,8}(date|day)", re.I),
)
_TIME_PATTERNS = (
    re.compile(r"(现在|当前).{0,8}(几点|时间|时刻|几时)"),
    re.compile(r"几点了"),
    re.compile(r"^现在几点"),
    re.compile(r"精确时间"),
    re.compile(r"what time", re.I),
)
_LOCATION_PATTERNS = (
    re.compile(r"(我在哪|我在哪里|什么城市|哪个城市|所在城市|定位)"),
    re.compile(r"(现在)?在(哪|哪里|什么地方)"),
    re.compile(r"where am i", re.I),
)

_EVAL_TOOL = "eval"
_BLOCKED_TOOLS_ON_INTENT = frozenset({_EVAL_TOOL})


@dataclass(frozen=True)
class SystemContextIntent:
    date: bool = False
    time: bool = False
    location: bool = False

    @property
    def any(self) -> bool:
        return self.date or self.time or self.location


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(p.search(text) for p in patterns)


def classify_system_context(text: str) -> SystemContextIntent:
    """识别简单日期/时间/位置事实问句（排除调研、落盘等复杂任务）。"""
    t = text.strip()
    if not t or t.startswith("/"):
        return SystemContextIntent()
    if len(t) > 120:
        return SystemContextIntent()
    lowered = t.casefold()
    if any(m.casefold() in lowered for m in _COMPLEX_MARKERS):
        return SystemContextIntent()
    if any(m.casefold() in lowered for m in _SCHEDULE_MARKERS):
        return SystemContextIntent()

    date = _matches_any(t, _DATE_PATTERNS)
    time = _matches_any(t, _TIME_PATTERNS)
    location = _matches_any(t, _LOCATION_PATTERNS)

    # 「今天」单独出现且很短 → 日期
    if not date and re.fullmatch(r"(今天|今日)[？?]?", t):
        date = True

    return SystemContextIntent(date=date, time=time, location=location)


def fetch_local_time(*, timeout: float = 15) -> str:
    """本机时间（Windows Get-Date，与 ADR execute 示例一致）。"""
    ps_cmd = (
        "$t = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; "
        "$z = [System.TimeZoneInfo]::Local.DisplayName; "
        "Write-Output ($t + ' (' + $z + ')')"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    out = (result.stdout or result.stderr or "").strip().replace("\r\n", " ")
    if not out:
        return "（无法读取本机时间）"
    return out


def fetch_location(*, timeout: float = 15) -> str:
    """IP 定位（curl ip-api，与 ADR execute 示例一致）。"""
    result = subprocess.run(
        ["curl", "-s", "http://ip-api.com/json/?lang=zh-CN"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    raw = (result.stdout or "").strip()
    if not raw:
        return "（无法读取 IP 定位）"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:200]
    if data.get("status") != "success":
        return raw[:200]
    parts = [p for p in (data.get("city"), data.get("regionName"), data.get("country")) if p]
    return "，".join(parts) if parts else raw[:200]


def format_date_answer(*, now: datetime | None = None) -> str:
    current = now or datetime.now()
    weekday = _WEEKDAYS[current.weekday()]
    return f"今天是 {current.strftime('%Y-%m-%d')}，{weekday}。"


def build_system_context_answer(
    intent: SystemContextIntent,
    *,
    now: datetime | None = None,
    time_fetcher: Callable[[], str] = fetch_local_time,
    location_fetcher: Callable[[], str] = fetch_location,
) -> str | None:
    if not intent.any:
        return None
    parts: list[str] = []
    if intent.date:
        parts.append(format_date_answer(now=now))
    if intent.time:
        parts.append(f"当前本机时间：{time_fetcher()}。")
    if intent.location:
        parts.append(f"根据本机 IP 定位：{location_fetcher()}。")
    return "\n".join(parts)


def wrong_tool_message(tool: str, intent: SystemContextIntent) -> str:
    hints: list[str] = []
    if intent.date:
        hints.append("问日期/星期 → 直接读 system prompt「今天是 …」")
    if intent.time:
        hints.append("问时间 → execute Get-Date")
    if intent.location:
        hints.append("问城市 → execute curl IP 定位")
    detail = "；".join(hints) or "请用 execute 读本机"
    return f"系统上下文问题禁止 {tool}。{detail}。（middleware 拦截）"


def last_human_from_messages(messages) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if isinstance(msg, dict) and msg.get("type") == "human":
            return str(msg.get("content", ""))
    return ""


def last_human_from_state(state) -> str:
    if not state:
        return ""
    messages = state.get("messages", []) if isinstance(state, dict) else getattr(state, "messages", [])
    return last_human_from_messages(messages)


class SystemContextEnforcerMiddleware(AgentMiddleware):
    """简单系统上下文问句 short-circuit + 拦截 eval/task(researcher) 误用。"""

    @property
    def name(self) -> str:
        return "system-context-enforcer"

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        text = last_human_from_state(state)
        intent = classify_system_context(text)
        if not intent.any:
            return None
        answer = build_system_context_answer(intent)
        if not answer:
            return None
        return {"jump_to": "end", "messages": [AIMessage(content=answer)]}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)

    def _blocked_tool(self, request) -> tuple[str, SystemContextIntent] | None:
        state = getattr(request, "state", None)
        intent = classify_system_context(last_human_from_state(state))
        if not intent.any:
            return None
        tool_call = getattr(request, "tool_call", None) or {}
        if not isinstance(tool_call, dict):
            return None
        tool = tool_call.get("name", "")
        args = tool_call.get("args", {}) or {}
        if tool in _BLOCKED_TOOLS_ON_INTENT:
            return tool, intent
        if tool == "task":
            subagent = str(
                args.get("subagent_type") or args.get("subagentType") or ""
            ).casefold()
            if subagent in ("researcher", "knowledge_keeper", "knowledge-keeper"):
                return tool, intent
        if tool == "read_file":
            path = _tool_arg_value(args, "file_path", "path")
            if "user-profile" in path.replace("\\", "/").casefold():
                return tool, intent
        return None

    def wrap_tool_call(self, request, handler):
        blocked = self._blocked_tool(request)
        if blocked:
            tool, intent = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=wrong_tool_message(tool, intent),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        blocked = self._blocked_tool(request)
        if blocked:
            tool, intent = blocked
            tool_call = getattr(request, "tool_call", None) or {}
            return ToolMessage(
                content=wrong_tool_message(tool, intent),
                name=tool,
                tool_call_id=tool_call.get("id", ""),
                status="error",
            )
        return await handler(request)
