"""#10 input_probe 纯函数单测：channel_line / format_key_event / format_record / doctor 行。

与 test_ime_shim 相同，依赖 Windows 专属的 textual.drivers.win32（INPUT_RECORD 结构体）。
"""

from __future__ import annotations

import ctypes

import textual.drivers.win32 as win32
from src import input_probe


def _make_record(event_type: int) -> win32.INPUT_RECORD:
    rec = win32.INPUT_RECORD()
    rec.EventType = event_type
    return rec


def _write_wchar(rec, offset_from_union: int, char: str) -> None:
    base = ctypes.addressof(rec) + input_probe._union_offset(rec) + offset_from_union
    ctypes.memmove(base, char.encode("utf-16-le"), len(char) * 2)


def _write_dword(rec, offset_from_union: int, value: int) -> None:
    base = ctypes.addressof(rec) + input_probe._union_offset(rec) + offset_from_union
    ctypes.memmove(base, value.to_bytes(4, "little"), 4)


def test_channel_line_cp936_conhost() -> None:
    line = input_probe.channel_line(936, 0x1)
    assert "CP=936" in line
    assert "conhost" in line
    assert "⚠" not in line


def test_channel_line_cp65001_pipe() -> None:
    line = input_probe.channel_line(65001, 0x2)
    assert "CP=65001" in line
    assert "PIPE" in line
    assert "⚠" not in line


def test_channel_line_bad_cp_warns() -> None:
    line = input_probe.channel_line(1252, 0x1)
    assert "CP=1252" in line
    assert "⚠" in line
    assert "勿自动修复" in line


def test_format_key_event_nul() -> None:
    rec = _make_record(input_probe.KEY_EVENT)
    ke = rec.Event.KeyEvent
    ke.bKeyDown = 1
    ke.wVirtualKeyCode = 0x27
    ke.wVirtualScanCode = 0x1E
    ke.uChar.UnicodeChar = "\x00"
    ke.dwControlKeyState = 0x0002
    line = input_probe.format_key_event(ke)
    assert "mod=0002" in line
    assert "down=1" in line
    assert "vk=27" in line
    assert "scan=1E" in line
    assert "<NUL>" in line


def test_format_key_event_char() -> None:
    rec = _make_record(input_probe.KEY_EVENT)
    ke = rec.Event.KeyEvent
    ke.bKeyDown = 1
    ke.wVirtualKeyCode = 0x41
    ke.uChar.UnicodeChar = "a"
    assert "uChar='a'" in input_probe.format_key_event(ke)


def test_format_record_unicode_event() -> None:
    rec = _make_record(input_probe.UNICODE_EVENT)
    _write_wchar(rec, 0, "\u201c")
    assert input_probe.format_record(rec) == "[UNICODE] U+201C"


def test_format_record_ime_event() -> None:
    rec = _make_record(input_probe.IME_EVENT)
    _write_dword(rec, 0, 0x0002)  # IMESF_COMMIT
    _write_wchar(rec, 4, "\u2026")
    line = input_probe.format_record(rec)
    assert "flags=0x2" in line
    assert "…" in line


def test_format_record_size_event() -> None:
    rec = _make_record(input_probe.WINDOW_BUFFER_SIZE_EVENT)
    rec.Event.WindowBufferSizeEvent.dwSize.X = 100
    rec.Event.WindowBufferSizeEvent.dwSize.Y = 40
    assert input_probe.format_record(rec) == "[SIZE] 100x40"


def test_doctor_line_safe_non_console() -> None:
    """/doctor 行：非控制台/管道环境下不抛异常，n/a 或正常行。"""
    line = input_probe.doctor_input_channel_line()
    assert line.startswith("输入通道:")
