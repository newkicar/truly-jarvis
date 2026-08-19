"""临时脚本：验证会话日期注入 vs 本机/UTC/execute。

用法: python tests/_manual/verify_session_date.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.agent import build_main_prompt, session_date_line  # noqa: E402


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> None:
    _section("1. Python datetime")
    local = datetime.now()
    utc = datetime.now(timezone.utc)
    shanghai = datetime.now(ZoneInfo("Asia/Shanghai"))
    print(f"datetime.now()              → {local.isoformat(sep=' ', timespec='seconds')}")
    print(f"datetime.now(timezone.utc)  → {utc.isoformat(sep=' ', timespec='seconds')}")
    print(f"Asia/Shanghai               → {shanghai.isoformat(sep=' ', timespec='seconds')}")
    print(f"local weekday (0=Mon)       → {local.weekday()}  UTC weekday → {utc.weekday()}")

    _section("2. 环境变量 TZ / 时区")
    print(f"TZ env                      → {os.environ.get('TZ', '(未设置)')}")
    try:
        ps_tz = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[System.TimeZoneInfo]::Local.Id + ' | ' + "
                "[System.TimeZoneInfo]::Local.DisplayName + ' | offset=' + "
                "[System.TimeZoneInfo]::Local.BaseUtcOffset",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        print(f"Windows Local TZ            → {ps_tz.stdout.strip() or ps_tz.stderr.strip()}")
    except Exception as exc:
        print(f"Windows Local TZ            → (失败) {exc}")

    _section("3. execute 等价：Get-Date")
    for label, cmd in [
        ("Get-Date (默认)", 'Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"'),
        ("Get-Date UTC", 'Get-Date -Format "yyyy-MM-dd HH:mm:ss" -AsUTC'),
        ("Get-Date 本地", 'Get-Date -Format "yyyy-MM-dd HH:mm:ss"'),
    ]:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            out = (r.stdout or r.stderr).strip().replace("\r\n", " | ")
            print(f"{label:20} → {out}")
        except Exception as exc:
            print(f"{label:20} → (失败) {exc}")

    _section("4. JARVIS prompt 注入（build_main_prompt 首行）")
    line = session_date_line()
    print(line)
    prompt_head = build_main_prompt().split("\n\n", 1)[0]
    print(f"\n{prompt_head}")

    _section("5. 对比结论")
    local_date = local.strftime("%Y-%m-%d")
    utc_date = utc.strftime("%Y-%m-%d")
    prompt_date = line.split()[1]  # 今天是 YYYY-MM-DD ...
    print(f"本机 local 日期             → {local_date}")
    print(f"UTC 日期                    → {utc_date}")
    print(f"prompt 注入日期             → {prompt_date}")
    if local_date == prompt_date:
        print("✓ prompt 与本机 local 一致")
    else:
        print("✗ prompt 与本机 local 不一致")
    if utc_date != local_date:
        print(f"⚠ UTC 与本机差一天：UTC={utc_date} local={local_date}（梯子/时区正常时可出现）")
    if prompt_date == utc_date and prompt_date != local_date:
        print("✗ 危险：prompt 用了 UTC 而非本机 local")
    elif prompt_date == local_date:
        print("→ 代理若答 UTC 日期，是模型自己编的，不是 prompt 注入错")


if __name__ == "__main__":
    main()
