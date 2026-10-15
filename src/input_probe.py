"""#10 输入通道探测：只读 dump 控制台每条 INPUT_RECORD（CJK IME 确认的原始形态）。

`python -m src.input_probe [out.txt]`（可选 `--timeout N`，默认 30s；Esc 或超时退出）。

用途：在你日常使用的终端（用户的 git bash / conhost / Windows Terminal）里跑一次，
输入几个中文汉字和若干全角标点，把输出回传；#11 的 ime_shim NUL-uChar 重建
最终形态按此记录形态定稿。

只读无副作用：仅 PeekConsoleInputW（不可用时回落 ReadConsoleInputW）；
绝不 SetConsoleCP（ConPTY 下 65000→65001 切换会破坏 IME），CP 异常仅告警。
/doctor 的「输入通道」诊断行复用 doctor_input_channel_line（只读）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

__all__ = [
    "channel_line",
    "doctor_input_channel_line",
    "format_key_event",
    "format_record",
    "main",
    "run",
]

# Windows 控制台输入记录类型（EVENT_TYPE，msdn INPUT_RECORD）
KEY_EVENT = 0x0001
WINDOW_BUFFER_SIZE_EVENT = 0x0004
UNICODE_EVENT = 0x0020
IME_EVENT = 0x0040

_EVENT_NAMES = {
    KEY_EVENT: "KEY",
    WINDOW_BUFFER_SIZE_EVENT: "SIZE",
    UNICODE_EVENT: "UNICODE",
    IME_EVENT: "IME",
}

# CJK IME 期望的控制台代码页（GBK / UTF-8）；其余仅告警，绝不 SetConsoleCP
_SAFE_CPS = {936, 65001}

_ESC_VK = 0x1B


def channel_line(cp: int, file_type: int) -> str:
    """输入通道诊断行（纯函数，可单测）：CP + stdin 句柄类型 + CP 异常告警。"""
    ft = {
        0: "unknown",
        0x1: "conhost 直连 (CHAR)",
        0x2: "pipe/ConPTY (PIPE)",
    }.get(file_type, f"0x{file_type:X}(?)")
    line = f"输入通道: CP={cp}, stdin={ft}"
    if cp not in _SAFE_CPS:
        line += " ⚠ CP 异常，CJK IME 可能受损（勿自动修复）"
    return line


def doctor_input_channel_line() -> str:
    """/doctor 一行：只读探测输入通道；非 Windows/无控制台句柄 → n/a。

    绝不自动 SetConsoleCP：ConPTY 下 65000→65001 切换会破坏 IME，CP 异常仅告警。
    """
    if sys.platform != "win32":
        return "输入通道: n/a（非 Windows）"
    try:
        from ctypes import windll

        kernel32 = windll.kernel32
        cp = int(kernel32.GetConsoleCP())
        ft = int(kernel32.GetFileType(os.gethandle(0)))
        return channel_line(cp, ft)
    except Exception:
        return "输入通道: n/a（无控制台句柄）"


def _union_offset(rec) -> int:
    """INPUT_RECORD 里 union 字段的字节偏移（运行时自 ctypes 类型动态读取，勿手算）。"""
    import ctypes

    return ctypes.addressof(rec.Event) - ctypes.addressof(rec)


def format_key_event(ke) -> str:
    """KEY_EVENT 一行（纯函数，可单测）：修饰键hex / bKeyDown / VK hex / scan / uChar（NUL 记作 <NUL>）。"""
    u_char = ke.uChar.UnicodeChar
    shown = "<NUL>" if not u_char or u_char == "\x00" else repr(u_char)
    return (
        f"mod={int(ke.dwControlKeyState):04X} down={int(bool(ke.bKeyDown))} "
        f"vk={int(ke.wVirtualKeyCode):02X} scan={int(ke.wVirtualScanCode):02X} uChar={shown}"
    )


def format_record(rec) -> str:
    """INPUT_RECORD 一行（纯函数，可单测；unicode/ime 按 union 原始字节读）。"""
    et = int(rec.EventType)
    name = _EVENT_NAMES.get(et, f"E{et:X}")
    if et == KEY_EVENT:
        return f"[{name}] {format_key_event(rec.Event.KeyEvent)}"
    off = _union_offset(rec)
    import ctypes

    base = ctypes.addressof(rec) + off
    if et == UNICODE_EVENT:
        ch = bytes((ctypes.c_ubyte * 2).from_address(base)).decode("utf-16-le", errors="ignore")
        return f"[UNICODE] U+{ord(ch):04X}" if ch else "[UNICODE] <empty>"
    if et == IME_EVENT:
        flags = int.from_bytes(bytes((ctypes.c_ubyte * 4).from_address(base)), "little")
        ch = bytes((ctypes.c_ubyte * 2).from_address(base + 4)).decode("utf-16-le", errors="ignore")
        return f"[IME] flags=0x{flags:X} wCharCode={ch!r}"
    if et == WINDOW_BUFFER_SIZE_EVENT:
        sz = rec.Event.WindowBufferSizeEvent.dwSize
        return f"[SIZE] {int(sz.X)}x{int(sz.Y)}"
    return f"[{name}]"


def _input_record_type():
    """自定义 INPUT_RECORD（msdn 布局，避免硬依赖 textual 驱动结构）。"""
    import ctypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class _UCHAR(ctypes.Union):
        _fields_ = [("AsciiChar", ctypes.c_char), ("UnicodeChar", ctypes.c_wchar)]

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("bKeyDown", ctypes.c_ushort),
            ("wRepeatCount", ctypes.c_ushort),
            ("wVirtualKeyCode", ctypes.c_ushort),
            ("wVirtualScanCode", ctypes.c_ushort),
            ("uChar", _UCHAR),
            ("dwControlKeyState", ctypes.c_uint),
        ]

    class MOUSE_EVENT_RECORD(ctypes.Structure):
        _fields_ = [
            ("dwMousePosition", COORD),
            ("dwButtonState", ctypes.c_uint),
            ("dwControlKeyState", ctypes.c_uint),
            ("dwEventFlags", ctypes.c_uint),
        ]

    class WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
        _fields_ = [("dwSize", COORD)]

    class MENU_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("dwCommandId", ctypes.c_uint)]

    class FOCUS_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bSetFocus", ctypes.c_ubyte)]

    class _EVENT(ctypes.Union):
        _fields_ = [
            ("KeyEvent", KEY_EVENT_RECORD),
            ("MouseEvent", MOUSE_EVENT_RECORD),
            ("WindowBufferSizeEvent", WINDOW_BUFFER_SIZE_RECORD),
            ("MenuEvent", MENU_EVENT_RECORD),
            ("FocusEvent", FOCUS_EVENT_RECORD),
        ]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", ctypes.c_ushort), ("Event", _EVENT)]

    return INPUT_RECORD


def run(out_path: Optional[str] = None, timeout: int = 30) -> int:
    """运行探测：逐条 dump 记录到 stdout（可选 out_path），Esc 或超时退出。

    返回读到的记录总数（环境错误返回 0）。只读：优先 PeekConsoleInputW（非阻塞），
    不可用则回落 ReadConsoleInputW（阻塞，超时近似）。
    """
    if sys.platform != "win32":
        print("input_probe 仅支持 Windows 控制台，本平台不探测。")
        return 0

    import ctypes
    from ctypes import byref, windll

    kernel32 = windll.kernel32
    cp = int(kernel32.GetConsoleCP())
    cp_out = int(kernel32.GetConsoleOutputCP())
    try:
        h_in = os.gethandle(0)
        ft = int(kernel32.GetFileType(h_in))
    except Exception:
        print("无法读取 stdin 句柄（非交互控制台？）")
        return 0

    lines = [
        f"input_probe {time.strftime('%Y-%m-%d %H:%M:%S')}",
        channel_line(cp, ft),
        f"(outCP={cp_out})",
        "请输入几个中文汉字与若干全角标点，Esc 或超时自动结束",
        "-" * 40,
    ]
    for ln in lines:
        print(ln, flush=True)

    rec_type = _input_record_type()
    MAX_EVENTS = 64
    buf = (rec_type * MAX_EVENTS)()
    count = ctypes.c_uint(0)
    try:
        peek = kernel32.PeekConsoleInputW
    except AttributeError:
        peek = None
    read = kernel32.ReadConsoleInputW

    counts = {}
    deadline = time.monotonic() + timeout
    esc_hit = False
    total = 0
    while time.monotonic() < deadline:
        count.value = 0
        if peek is not None:
            ok = int(peek(h_in, buf, MAX_EVENTS, byref(count)))
        else:
            ok = int(read(h_in, buf, MAX_EVENTS, byref(count)))
        if not ok or not count.value:
            time.sleep(0.05)
            continue
        for i in range(count.value):
            rec = buf[i]
            et = int(rec.EventType)
            counts[et] = counts.get(et, 0) + 1
            total += 1
            line = format_record(rec)
            lines.append(line)
            print(line, flush=True)
            if et == KEY_EVENT and int(rec.Event.KeyEvent.bKeyDown) and int(rec.Event.KeyEvent.wVirtualKeyCode) == _ESC_VK:
                esc_hit = True
                break
        if esc_hit:
            break

    summary = ", ".join(f"{_EVENT_NAMES.get(k, f'E{k:X}')}={v}" for k, v in sorted(counts.items()))
    tail = [
        "-" * 40,
        f"汇总: {summary or '无记录'} | outCP={cp_out} | 结束方式={'Esc' if esc_hit else '超时'}",
        channel_line(cp, ft),
    ]
    for ln in tail:
        print(ln, flush=True)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines + tail) + "\n")
        print(f"已写入 {out_path}", flush=True)
    return total


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="输入通道探测：只读 dump 控制台 INPUT_RECORD（Esc/超时退出）")
    parser.add_argument("out", nargs="?", default=None, help="输出文件路径（可选，缺省仅打印到屏幕）")
    parser.add_argument("--timeout", type=int, default=30, help="超时秒数（默认 30）")
    args = parser.parse_args(argv)
    run(out_path=args.out, timeout=args.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
