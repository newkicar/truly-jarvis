"""本地系统上下文：日期与时间（按需读取，不注入 system prompt）。"""
from __future__ import annotations

import json
from datetime import datetime

from langchain_core.tools import tool

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


def read_system_context(*, now: datetime | None = None) -> dict[str, str]:
    """读取当前本地日期与时间。"""
    current = now or datetime.now()
    return {
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M:%S"),
        "datetime": current.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": _WEEKDAYS[current.weekday()],
    }


def format_system_context(ctx: dict[str, str]) -> str:
    """人类可读单行摘要。"""
    return f"{ctx['datetime']}（{ctx['weekday']}）"


def make_get_system_context_tool():
    """主代理专用：读取当前日期时间，供 system-context skill 调用（无需 execute）。"""

    @tool
    def get_system_context() -> str:
        """Return current local date, time, and weekday as JSON.

        Call when the user asks what time or date it is now.
        """
        return json.dumps(read_system_context(), ensure_ascii=False)

    return get_system_context
