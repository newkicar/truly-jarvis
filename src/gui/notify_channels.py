"""gui 任务完成通知平台通道（gui bgnotify；Windows 实现，非 Win 返回 skipped）。

三通道（纯 stdlib，无 Qt 依赖）：
- sound: ctypes MessageBeep（系统提示音）
- voice: PowerShell + System.Speech (SAPI) 语音播报
- email: Outlook COM（CreateItem(0) + Send，非交互直发；Outlook 未装 → error 状态串）

所有 PowerShell 值经 _ps_literal（单引号翻倍）注入；脚本不含裸反引号。
"""
from __future__ import annotations

import base64
import os
import subprocess

_PS_TIMEOUT_S = 120


def _is_windows() -> bool:
    return os.name == "nt"


def _message_beep() -> None:
    """MessageBeep(0x40) 系统消息音（独立 seam 便于测试 fake）。"""
    import ctypes

    ctypes.windll.winmm.MessageBeep(0x40)


def _powershell(script: str) -> str:
    """跑 -EncodedCommand（UTF-16LE base64，中文值安全）；rc≠0 抛 RuntimeError。"""
    b64 = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", b64],
        capture_output=True,
        text=True,
        timeout=_PS_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "").strip()[:200])
    return proc.stdout


def _ps_literal(value) -> str:
    """PS 单引号字符串字面量（单引号翻倍；反引号在单引号串内无需转义）。"""
    return "'" + str(value).replace("'", "''") + "'"


def play_sound() -> str:
    """通道：提示音。非 Windows → skipped 状态串（不崩）。"""
    if not _is_windows():
        return "skipped-non-windows"
    try:
        _message_beep()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"


def speak(text: str) -> str:
    """通道：SAPI 语音播报（PowerShell + System.Speech）。"""
    if not _is_windows():
        return "skipped-non-windows"
    script = (
        "Add-Type -AssemblyName System.Speech;"
        " $s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        " $s.Speak(" + _ps_literal(text) + ");"
        " [void]$s.Dispose()"
    )
    try:
        _powershell(script)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"


def send_outlook_email(to: str, subject: str, body: str) -> str:
    """通道：Outlook COM 直发邮件（Send 非 Display；to 空先于平台判断）。"""
    if not to:
        return "skipped:no-recipient"
    if not _is_windows():
        return "skipped-non-windows"
    script = (
        "$o = New-Object -ComObject Outlook.Application;"
        " $m = $o.CreateItem(0);"
        f" $m.To = {_ps_literal(to)};"
        f" $m.Subject = {_ps_literal(subject)};"
        f" $m.Body = {_ps_literal(body)};"
        " $m.Send()"
    )
    try:
        _powershell(script)
        return "ok"
    except Exception as exc:  # noqa: BLE001 — Outlook 未装/异常 → 状态串，不崩
        return f"error:{exc}"


def make_hooks() -> dict:
    """三通道函数表（键名对齐 NotificationPolicy 开关；调用时查模块级，monkeypatch 生效）。"""
    g = globals()
    return {
        "sound": g["play_sound"],
        "voice": g["speak"],
        "email": g["send_outlook_email"],
    }
