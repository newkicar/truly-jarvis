"""#02: conhost IME/Unicode 输入补全 shim（Textual win32 驱动读循环补全）。

Textual 8.2.8 的 win32 EventMonitor 读循环只处理 KEY_EVENT(0x0001) 与
WINDOW_BUFFER_SIZE_EVENT(0x0004) 两类控制台输入记录；console 在输入法确认
组合字符时发出的 UNICODE_EVENT(0x0020) / IME_EVENT(0x0040) 被静默丢弃。

现象：conhost 里物理键直接映射的全角标点（，。、等）走 KEY_EVENT.UnicodeChar
可以正常输入；但需要输入法组合确认的字符（“ ” ‘ ’ … 等）以 UNICODE_EVENT
记录下发，进不了应用——用户报告的「中文双引号单引号输入不进去」。

NUL-uChar 重建（#11）：部分 ConPTY/IME 组合下确认字符会以 uChar 为 NUL 的
KEY_EVENT 下发；此时用 MapVirtualKeyW(VK) 重建字符，仅当「无真实修饰键按下
（dwControlKeyState & 0x00F8：Shift/Ctrl/Alt 未按下；NumLock/ScrollLock/Enhanced
非修饰键，不阻挡重建）+ 结果非 ASCII」才并入字符流（ord≥0x80 子包控制键检查），
最终形态以 #10 input_probe 探测输出为准。

install()（仅 win32，幂等）monkey-patch EventMonitor.run：保留原有按键处理
与窗口尺寸逻辑，另把 UNICODE_EVENT/IME_EVENT 记录并入按键字符流，走同一
parser.feed 路径。

安全约束：
- 纯函数核心 fold_input_records 可单测（合成 ctypes INPUT_RECORD）。
- patch 前校验原 run 源码仍含 ReadConsoleInputW 签名行；textual 升级
  改形时跳过 patch（不静默漂移），启动日志提示面板兜底。
"""

from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING, List, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查
    from textual.drivers.win32 import INPUT_RECORD

__all__ = [
    "fold_input_records",
    "install",
    "shim_status",
    "ensure",
    "union_offset",
]

# Windows 控制台输入记录类型（EVENT_TYPE，msdn INPUT_RECORD）
KEY_EVENT = 0x0001
WINDOW_BUFFER_SIZE_EVENT = 0x0004
UNICODE_EVENT = 0x0020
IME_EVENT = 0x0040

# IME_KEY_RECORD.dwEventFlags（IMESF_*，msdn IME_KEY_RECORD）
IMESF_COMP = 0x1  # 组合中（pre-edit）字符
IMESF_COMMIT = 0x2  # 上屏（确认）字符
IMESF_END = 0x4  # 组合结束（union 里是 dwEventId，无字符）

_UNION_OFFSET: Optional[int] = None


def union_offset() -> int:
    """INPUT_RECORD 里 union 字段的实际字节偏移（运行时自 ctypes 结构读，勿手算）。"""
    global _UNION_OFFSET
    if _UNION_OFFSET is None:
        import textual.drivers.win32 as win32

        rec = win32.INPUT_RECORD()
        _UNION_OFFSET = ctypes.addressof(rec.Event) - ctypes.addressof(rec)
    return _UNION_OFFSET


def _map_vk(vk: int) -> str:
    """VK → 字符（Win32 MapVirtualKeyW(vk, 0)）；非 win32/失败/无字符键返回 "".

    #11 NUL-uChar 重建（ConPTY IME 确认记录形态）；单测 monkeypatch 本函数。
    """
    if sys.platform != "win32":
        return ""
    if not isinstance(vk, int) or vk <= 0 or vk > 0xFFFF:
        return ""
    try:
        from ctypes import windll

        code = windll.user32.MapVirtualKeyW(vk, 0)
    except Exception:
        return ""
    if not code:
        return ""
    ch = chr(code)
    return "" if ch == "\x00" else ch


def _read_wchar_at(base: int, offset: int) -> str:
    raw = bytes((ctypes.c_ubyte * 2).from_address(base + offset))
    return raw.decode("utf-16-le", errors="ignore")


def fold_input_records(
    records: Sequence["INPUT_RECORD"],
) -> tuple[List[str], Optional[tuple[int, int]]]:
    """把一批 INPUT_RECORD 折叠成 (按键字符流, 窗口尺寸)。纯函数，供单测。

    与 Textual 8.2.8 原循环的差异（也是本模块存在的意义）：
    - UNICODE_EVENT：取 union 首个 WCHAR（UnicodeChar）并入字符流；
    - IME_EVENT：仅 IMESF_COMMIT 时取 union 偏移 +4 的 wCharCode 并入；
      IMESF_COMP（pre-edit 组合字）与 IMESF_END 不并入——pre-edit 逐字
      上屏会闪烁/重影，console 自带 IME 窗已展示组合过程。
    - KEY_EVENT NUL-uChar（#11）：UnicodeChar 为 NUL/空（ConPTY IME 确认记录形态）时，
      经 MapVirtualKeyW(VK) 重建字符，仅「无真实修饰键按下（dwControlKeyState & 0x00F8 == 0；
      0x00F8 = Ctrl_L/R|Alt_L/R|Shift_L/R 实按位；NumLock(0x0001)/ScrollLock(0x0002)/
      Enhanced(0x0004) 非真实修饰键，NumLock 开启是常态，误含即整段字符流丢失）
      且结果非 ASCII（ord≥0x80）」才并入；正常 uChar 原样追加，不再追加空串。
    """
    off = union_offset()
    keys: List[str] = []
    new_size: Optional[tuple[int, int]] = None
    for rec in records:
        event_type = rec.EventType
        if event_type == KEY_EVENT:
            key_event = rec.Event.KeyEvent
            if not key_event.bKeyDown:
                continue
            # 与原循环一致：修饰键单独按下（无字符、非虚拟键）跳过
            if key_event.dwControlKeyState and key_event.wVirtualKeyCode == 0:
                continue
            u_char = key_event.uChar.UnicodeChar
            if not u_char or u_char == "\x00":
                # #11 NUL-uChar 重建（ConPTY IME 确认记录形态）：
                # MapVirtualKeyW(VK) 重建字符，仅「无真实修饰键按下 + 非 ASCII」才并入。
                # 0x00F8 = Ctrl_L/R|Alt_L/R|Shift_L/R 实按位；0x0007（NumLock/ScrollLock/
                # Enhanced）非真实修饰键——误含会在 NumLock 开启时静默丢失整段 IME 确认字符。
                rebuilt = _map_vk(key_event.wVirtualKeyCode)
                if rebuilt and ord(rebuilt) >= 0x80 and not (key_event.dwControlKeyState & 0x00F8):
                    keys.append(rebuilt)
            else:
                keys.append(u_char)
        elif event_type == UNICODE_EVENT:
            ch = _read_wchar_at(ctypes.addressof(rec), off)
            if ch:
                keys.append(ch)
        elif event_type == IME_EVENT:
            base = ctypes.addressof(rec)
            flags = int.from_bytes(bytes((ctypes.c_ubyte * 4).from_address(base + off)), "little")
            if flags & IMESF_COMMIT:
                ch = _read_wchar_at(base, off + 4)
                if ch:
                    keys.append(ch)
        elif event_type == WINDOW_BUFFER_SIZE_EVENT:
            size = rec.Event.WindowBufferSizeEvent.dwSize
            new_size = (size.X, size.Y)
    return keys, new_size


def _patched_run(self) -> None:
    """原 EventMonitor.run 副本 + UNICODE_EVENT/IME_EVENT 补全（模块 docstring）。"""
    import textual.drivers.win32 as mod

    exit_requested = self.exit_event.is_set
    parser = mod.XTermParser(debug=mod.constants.DEBUG)
    try:
        read_count = mod.wintypes.DWORD(0)
        hIn = mod.GetStdHandle(mod.STD_INPUT_HANDLE)
        MAX_EVENTS = 1024
        arrtype = mod.INPUT_RECORD * MAX_EVENTS
        input_records = arrtype()
        ReadConsoleInputW = mod.KERNEL32.ReadConsoleInputW

        while not exit_requested():
            for event in parser.tick():
                self.process_event(event)

            if mod.wait_for_handles([hIn], 100) is None:
                continue

            ReadConsoleInputW(hIn, ctypes.byref(input_records), MAX_EVENTS, ctypes.byref(read_count))
            read_input_records = input_records[: read_count.value]

            keys, new_size = fold_input_records(read_input_records)
            if keys:
                # 与原循环相同的 utf-16 往返（textual issue #3178）
                for event in parser.feed(
                    "".join(keys).encode("utf-16", "surrogatepass").decode("utf-16")
                ):
                    self.process_event(event)
            if new_size is not None:
                self.on_size_change(*new_size)

    except Exception as error:  # noqa: BLE001 - 与原实现一致：吞掉并在日志留痕
        self.app.log.error("EVENT MONITOR ERROR", error)


def install() -> bool:
    """安装 IME/Unicode 补全 shim（仅 win32，幂等）。

    返回 True=已生效或无需操作（非 win32/已装/原实现签名已变但本终端不受影响
    时按实际情况），False=未能安装（textual 改形，需人工复核）。
    """
    if sys.platform != "win32":
        return True  # 非 Windows 无此驱动，无需 shim
    try:
        import textual.drivers.win32 as mod
    except ImportError:  # pragma: no cover
        return False

    if getattr(mod.EventMonitor, "_jarvis_ime_shim", False):
        return True  # 幂等

    import inspect

    orig_src = inspect.getsource(mod.EventMonitor.run)
    if "ReadConsoleInputW" not in orig_src:
        # textual 大改读循环：不盲目 patch，避免静默漂移
        mod.EventMonitor._jarvis_ime_drift = True  # type: ignore[attr-defined]
        return False
    mod.EventMonitor.run = _patched_run  # type: ignore[attr-defined]
    mod.EventMonitor._jarvis_ime_shim = True  # type: ignore[attr-defined]
    return True


def shim_status() -> str:
    """tui-ux13: 纯函数读 EventMonitor 属性 → "installed" / "drifted" / "absent"。

    非 win32 或 textual.win32 模块缺失/导入失败 → "absent"。可 fake 模块属性单测。
    """
    if sys.platform != "win32":
        return "absent"
    try:
        import textual.drivers.win32 as mod
    except Exception:  # noqa: BLE001
        return "absent"
    if not getattr(mod.EventMonitor, "_jarvis_ime_shim", False):
        return "absent"
    if getattr(mod.EventMonitor, "_jarvis_ime_drift", False):
        return "drifted"
    return "installed"


def ensure() -> str:
    """tui-ux13: 低频复检入口（幂等）。

    absent → install；drifted → 清 _jarvis_ime_drift 后重装；installed → no-op。
    返回装配后的新状态（shim_status()），替代 main.py 一次性 install。
    """
    status = shim_status()
    if status == "drifted":
        try:
            import textual.drivers.win32 as mod
            mod.EventMonitor._jarvis_ime_drift = False  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    install()
    return shim_status()
