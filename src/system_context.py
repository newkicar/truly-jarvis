"""本地系统上下文：日期、时间与 IP 推算城市（按需读取，不注入 system prompt）。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable

import httpx
from langchain_core.tools import tool

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_GEO_TIMEOUT = 5.0
_GEO_URL = "http://ip-api.com/json/?lang=zh-CN"


def lookup_geo_from_ip(*, client: httpx.Client | None = None) -> dict[str, str]:
    """通过公网 IP 推算城市（ISP 级精度，非 GPS）。"""
    empty = {
        "ip": "",
        "city": "",
        "region": "",
        "country": "",
        "location": "",
        "location_source": "unavailable",
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=_GEO_TIMEOUT)
    try:
        resp = http.get(_GEO_URL)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, OSError, json.JSONDecodeError, ValueError):
        return empty
    finally:
        if owns_client:
            http.close()

    if data.get("status") != "success":
        return empty

    city = str(data.get("city") or "").strip()
    region = str(data.get("regionName") or "").strip()
    country = str(data.get("country") or "").strip()
    ip = str(data.get("query") or "").strip()
    parts = [p for p in (city, region, country) if p]
    location = "，".join(dict.fromkeys(parts))  # 去重保序

    return {
        "ip": ip,
        "city": city,
        "region": region,
        "country": country,
        "location": location,
        "location_source": "ip-api",
    }


def read_system_context(
    *,
    now: datetime | None = None,
    geo_lookup: Callable[[], dict[str, str]] | None = None,
    include_location: bool = True,
) -> dict[str, str]:
    """读取当前本地日期、时间与 IP 推算城市。"""
    current = now or datetime.now()
    ctx: dict[str, str] = {
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M:%S"),
        "datetime": current.strftime("%Y-%m-%d %H:%M:%S"),
        "weekday": _WEEKDAYS[current.weekday()],
    }
    if include_location:
        lookup = geo_lookup or lookup_geo_from_ip
        ctx.update(lookup())
    return ctx


def format_system_context(ctx: dict[str, str]) -> str:
    """人类可读单行摘要。"""
    text = f"{ctx['datetime']}（{ctx['weekday']}）"
    location = ctx.get("location", "").strip()
    if location:
        text += f"，{location}"
    return text


def make_get_system_context_tool():
    """主代理专用：读取日期时间与 IP 推算城市，供 system-context skill 调用。"""

    @tool
    def get_system_context() -> str:
        """Return local date, time, weekday, and approximate city from public IP as JSON.

        Call when the user asks what time/date it is, or where they are (city level).
        """
        return json.dumps(read_system_context(), ensure_ascii=False)

    return get_system_context
