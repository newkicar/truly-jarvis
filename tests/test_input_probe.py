"""#10 input_probe 纯函数单测：channel_line / format_key_event / format_record / doctor 行。

与 test_ime_shim 相同，依赖 Windows 专属的 textual.drivers.win32（INPUT_RECORD 结构体）。
"""

from __future__ import annotations

import sys

import pytest

if sys.platform != "win32":
    pytest.skip(
        "Windows-only test (textual win32 driver / msvcrt)",
        allow_module_level=True,
    )

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


def test_doctor_lines_safe_non_console() -> None:
    """/doctor 输入通道 2 行（tui-ux13）：非控制台 / 管道环境不抛错，首行以「输入通道」开头。"""
    lines = input_probe.doctor_input_channel_lines()
    assert isinstance(lines, list) and lines
    assert all(isinstance(x, str) for x in lines)
    assert lines[0].startswith("输入通道")


@pytest.mark.parametrize(
    ("wt_session", "ft", "expect"),
    [
        ("1", 0x1, "终端=Windows Terminal"),
        (None, 0x1, "终端=conhost"),
        (None, 0x2, "终端=pipe/ConPTY"),
        (None, 0x7, "终端=未知(0x7)"),
    ],
)
def test_terminal_type_line_table(monkeypatch, wt_session, ft, expect) -> None:
    monkeypatch.delenv("WT_SESSION", raising=False)
    if wt_session is not None:
        monkeypatch.setenv("WT_SESSION", wt_session)
    assert input_probe.terminal_type_line(ft) == expect


def test_summarize_session_channel_reachable() -> None:
    counts = {input_probe.KEY_EVENT: 5, input_probe.UNICODE_EVENT: 2}
    lines = input_probe.summarize_session(counts, 0, 936, "Esc")
    assert lines[0] == "直方图: KEY=5 UNICODE=2 IME=0 NUL-uChar=0 | 结束方式=Esc"
    assert "中文确认通道可达" in lines[1] and "⚠" not in lines[1]


def test_summarize_session_nul_rebuild_state() -> None:
    lines = input_probe.summarize_session({input_probe.KEY_EVENT: 9}, 3, 936, "Esc")
    assert "NUL-uChar 重建" in lines[1] and "ime_shim" in lines[1]
    assert "可达" not in lines[1]


def test_summarize_session_not_observed_state() -> None:
    lines = input_probe.summarize_session({input_probe.KEY_EVENT: 9}, 0, 65001, "Timeout")
    assert "未观察到中文 IME 记录" in lines[1] and "Ctrl+." in lines[1]


def test_summarize_session_cp_warn_all_states() -> None:
    l1 = input_probe.summarize_session({input_probe.UNICODE_EVENT: 1}, 0, 1252, "Timeout")
    assert "⚠" in l1[1] and "勿自动修复" in l1[1]
    l2 = input_probe.summarize_session({input_probe.KEY_EVENT: 3}, 4, 1252, "Timeout")
    assert "⚠" in l2[1]
    l3 = input_probe.summarize_session({input_probe.KEY_EVENT: 3}, 0, 1252, "Timeout")
    assert "⚠" in l3[1]


def test_summarize_session_empty_counts() -> None:
    lines = input_probe.summarize_session({}, 0, 936, "Timeout")
    assert lines[0] == "直方图: KEY=0 UNICODE=0 IME=0 NUL-uChar=0 | 结束方式=Timeout"
    assert "未观察到中文 IME 记录" in lines[1]
