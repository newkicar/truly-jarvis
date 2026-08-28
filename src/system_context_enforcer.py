"""系统上下文强制层（ADR-0003）。

仅对纯日期/星期问句 short-circuit（读 system prompt 首行）。
eval 若用于探测系统时钟（代码特征），在工具层温和重定向——不按用户问法分类。
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from langchain.agents.middleware.types import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage

from src.guard import GuardMiddleware
from src.tool_call import ToolCallView

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
_CLOCK_EVAL_PATTERNS = (
    re.compile(r"\bnew\s+Date\b", re.I),
    re.compile(r"\bDate\.now\b", re.I),
    re.compile(r"toISOString|toLocaleString|getTimezoneOffset", re.I),
    re.compile(r"Get-Date|System\.TimeZoneInfo", re.I),
)

_EVAL_TOOL = "eval"


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

    if not date and re.fullmatch(r"(今天|今日)[？?]?", t):
        date = True

    return SystemContextIntent(date=date, time=time, location=location)


def eval_code_looks_like_clock_probe(code: str) -> bool:
    """eval 代码是否在探测时钟/时区（工具层特征，与用户问法无关）。"""
    return _matches_any(str(code or ""), _CLOCK_EVAL_PATTERNS)


def eval_misuse_message() -> str:
    return (
        "eval 用于代码计算，不用于读取系统时钟或环境。"
        "本机信息用 execute；需外部信息用 quick_search。"
    )


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


class SystemContextEnforcerMiddleware(GuardMiddleware):
    """纯日期 short-circuit；eval 时钟探测代码在工具层重定向。"""

    @property
    def name(self) -> str:
        return "system-context-enforcer"

    @hook_config(can_jump_to=["end"])
    def before_model(self, state, runtime):
        text = last_human_from_state(state)
        intent = classify_system_context(text)
        if not intent.date or intent.time or intent.location:
            return None
        return {"jump_to": "end", "messages": [AIMessage(content=format_date_answer())]}

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state, runtime):
        return self.before_model(state, runtime)

    def block(self, view: ToolCallView) -> str | None:
        if view.name == _EVAL_TOOL:
            code = str(view.args.get("code") or view.args.get("expression") or "")
            if eval_code_looks_like_clock_probe(code):
                return eval_misuse_message()
        if view.name == "read_file":
            path = view.arg_value("file_path", "path")
            if "user-profile" in path.replace("\\", "/").casefold():
                return "不要读 user-profile 推断用户状况；用工具自行核实。"
        return None
