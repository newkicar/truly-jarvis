"""#02 IME/Unicode patch shim unit tests: fold_input_records pure function + install behavior.

Synthesize ctypes INPUT_RECORD (Windows 64-bit: sizeof=20, union offset 4) to verify that
UNICODE_EVENT/IME_EVENT records get folded into the key character stream — this is exactly
the root-cause path for why Chinese combined punctuation (“ ” ‘ ’ …) can't get into Textual's input box under conhost.
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
import inspect

import textual.drivers.win32 as win32
from src import ime_shim


def _make_record(event_type: int) -> win32.INPUT_RECORD:
    rec = win32.INPUT_RECORD()
    rec.EventType = event_type
    return rec

def _write_wchar(rec: win32.INPUT_RECORD, offset_from_union: int, char: str) -> None:
    """按 Windows 控制台记录布局，在 union 内指定偏移写 WCHAR（UTF-16LE）。"""
    base = ctypes.addressof(rec) + ime_shim.union_offset() + offset_from_union
    raw = char.encode("utf-16-le")
    ctypes.memmove(base, raw, len(raw))


def _write_dword(rec: win32.INPUT_RECORD, offset_from_union: int, value: int) -> None:
    base = ctypes.addressof(rec) + ime_shim.union_offset() + offset_from_union
    ctypes.memmove(base, value.to_bytes(4, "little"), 4)

# ---- fold_input_records：记录类型 → 字符流 ----


def test_key_event_char_unchanged() -> None:
    """原有 KEY_EVENT 路径行为不变：按下且无修饰键特例时收字符。"""
    rec = _make_record(ime_shim.KEY_EVENT)
    ke = rec.Event.KeyEvent
    ke.bKeyDown = 1
    ke.wRepeatCount = 1
    ke.wVirtualKeyCode = 0x41  # 'a'
    ke.wVirtualScanCode = 0
    ke.uChar.UnicodeChar = "a"
    ke.dwControlKeyState = 0
    keys, size = ime_shim.fold_input_records([rec])
    assert keys == ["a"] and size is None


def test_key_event_keyup_ignored() -> None:
    rec = _make_record(ime_shim.KEY_EVENT)
    rec.Event.KeyEvent.bKeyDown = 0
    rec.Event.KeyEvent.uChar.UnicodeChar = "a"
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_key_event_modifier_alone_skipped() -> None:
    """修饰键单独按下（无字符且 wVirtualKeyCode==0）跳过，与原循环一致。"""
    rec = _make_record(ime_shim.KEY_EVENT)
    ke = rec.Event.KeyEvent
    ke.bKeyDown = 1
    ke.dwControlKeyState = 0x10
    ke.wVirtualKeyCode = 0
    ke.uChar.UnicodeChar = "\x00"
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_unicode_event_char_extracted() -> None:
    """UNICODE_EVENT：console 下发的组合确认字符（如 “）并入字符流。"""
    rec = _make_record(ime_shim.UNICODE_EVENT)
    _write_wchar(rec, 0, "\u201c")  # 左双引号
    keys, size = ime_shim.fold_input_records([rec])
    assert keys == ["\u201c"] and size is None

def test_ime_commit_char_extracted() -> None:
    """IME_EVENT + IMESF_COMMIT：union 偏移 +4 的 wCharCode 并入。"""
    rec = _make_record(ime_shim.IME_EVENT)
    _write_dword(rec, 0, ime_shim.IMESF_COMMIT)
    _write_wchar(rec, 4, "\u3002")  # 。
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == ["\u3002"]


def test_ime_composition_not_inserted() -> None:
    """IME_EVENT + IMESF_COMP（pre-edit）不并入——避免组合过程逐字上屏。"""
    rec = _make_record(ime_shim.IME_EVENT)
    _write_dword(rec, 0, ime_shim.IMESF_COMP)
    _write_wchar(rec, 4, "\u4e2d")
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_ime_end_not_inserted() -> None:
    """IME_EVENT + IMESF_END：union 里是 dwEventId（无字符），不并入。"""
    rec = _make_record(ime_shim.IME_EVENT)
    _write_dword(rec, 0, ime_shim.IMESF_END)
    _write_dword(rec, 4, 12345)  # dwEventId
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_size_event_reported() -> None:
    rec = _make_record(ime_shim.WINDOW_BUFFER_SIZE_EVENT)
    rec.Event.WindowBufferSizeEvent.dwSize.X = 120
    rec.Event.WindowBufferSizeEvent.dwSize.Y = 40
    keys, size = ime_shim.fold_input_records([rec])
    assert keys == [] and size == (120, 40)


def test_mixed_batch_ordering() -> None:
    """混合批：按键 + UNICODE + IME_COMMIT 顺序保持。"""
    rec_a = _make_record(ime_shim.KEY_EVENT)
    rec_a.Event.KeyEvent.bKeyDown = 1
    rec_a.Event.KeyEvent.wVirtualKeyCode = 0x41
    rec_a.Event.KeyEvent.uChar.UnicodeChar = "a"
    rec_u = _make_record(ime_shim.UNICODE_EVENT)
    _write_wchar(rec_u, 0, "\u201d")  # 右双引号
    rec_i = _make_record(ime_shim.IME_EVENT)
    _write_dword(rec_i, 0, ime_shim.IMESF_COMMIT)
    _write_wchar(rec_i, 4, "\u2026")  # …
    keys, _ = ime_shim.fold_input_records([rec_a, rec_u, rec_i])
    assert keys == ["a", "\u201d", "\u2026"]

# ---- install：幂等 + 改形保护 ----


def test_install_idempotent() -> None:
    assert ime_shim.install() is True
    assert getattr(win32.EventMonitor, "_jarvis_ime_shim", False) is True
    patched_first = win32.EventMonitor.run
    assert ime_shim.install() is True
    assert win32.EventMonitor.run is patched_first


def test_install_skipped_when_original_run_drifted(monkeypatch) -> None:
    """原 run 源码不再含 ReadConsoleInputW（textual 改形）时不 patch。"""
    monkeypatch.setattr(inspect, "getsource", lambda f: "def run(self): ...")
    for attr in ("_jarvis_ime_shim", "_jarvis_ime_drift"):
        if hasattr(win32.EventMonitor, attr):
            delattr(win32.EventMonitor, attr)
    assert ime_shim.install() is False
    assert getattr(win32.EventMonitor, "_jarvis_ime_drift", False) is True

# ---- #11 NUL-uChar 重建（ConPTY IME 确认记录形态） ----


def _set_key(rec, vk=0, scan=0, u_char="", mods=0, down=1):
    ke = rec.Event.KeyEvent
    ke.bKeyDown = down
    ke.wVirtualKeyCode = vk
    ke.wVirtualScanCode = scan
    ke.uChar.UnicodeChar = u_char
    ke.dwControlKeyState = mods


def test_nul_u_char_rebuilt_cjk_merged(monkeypatch) -> None:
    """NUL-uChar + 无修饰键 + 重建结果非 ASCII：并入字符流。"""
    monkeypatch.setattr(ime_shim, "_map_vk", lambda vk: "\u201c")  # “
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0x27, u_char="\x00")
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == ["\u201c"]


def test_nul_u_char_with_shift_not_merged(monkeypatch) -> None:
    """NUL-uChar + LEFT_SHIFT_PRESSED 按下（0x0080）：不并入。"""
    monkeypatch.setattr(ime_shim, "_map_vk", lambda vk: "\u201c")
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0x27, u_char="\x00", mods=0x0080)
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_nul_u_char_with_numlock_merged(monkeypatch) -> None:
    """NUL-uChar + 只 NumLock(0x0001，非真实修饰键)按下：仍并入。NumLock 开启是常态，错阻则静默丢失整段 IME 确认字符。"""
    monkeypatch.setattr(ime_shim, "_map_vk", lambda vk: "\u201c")
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0x27, u_char="\x00", mods=0x0001)
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == ["\u201c"]


def test_nul_u_char_ascii_result_ignored(monkeypatch) -> None:
    """NUL-uChar 但重建结果 ASCII：不并入（ASCII 键走正常路径）。"""
    monkeypatch.setattr(ime_shim, "_map_vk", lambda vk: "a")
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0x41, u_char="\x00")
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_nul_u_char_unmapped_vk_ignored(monkeypatch) -> None:
    """NUL-uChar 且 MapVirtualKeyW 无法映射（返回空）：不并入、不炸。"""
    monkeypatch.setattr(ime_shim, "_map_vk", lambda vk: "")
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0x70, u_char="\x00")
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == []


def test_normal_u_char_regression_unchanged() -> None:
    """回归：正常 uChar（，）仍原样追加，不进重建路径。"""
    rec = _make_record(ime_shim.KEY_EVENT)
    _set_key(rec, vk=0xBA, u_char="，")
    keys, _ = ime_shim.fold_input_records([rec])
    assert keys == ["，"]


# ---- tui-ux13: shim_status three states + ensure idempotent recheck (L1) ----


def _clear_shim_flags() -> None:
    for attr in ("_jarvis_ime_shim", "_jarvis_ime_drift"):
        if hasattr(win32.EventMonitor, attr):
            delattr(win32.EventMonitor, attr)


def test_shim_status_absent() -> None:
    _clear_shim_flags()
    assert ime_shim.shim_status() == "absent"


def test_shim_status_drifted() -> None:
    _clear_shim_flags()
    win32.EventMonitor._jarvis_ime_shim = True
    win32.EventMonitor._jarvis_ime_drift = True
    assert ime_shim.shim_status() == "drifted"


def test_shim_status_installed_after_install() -> None:
    _clear_shim_flags()
    assert ime_shim.install() is True
    assert ime_shim.shim_status() == "installed"


def test_ensure_absent_installs() -> None:
    _clear_shim_flags()
    assert ime_shim.shim_status() == "absent"
    assert ime_shim.ensure() == "installed"
    assert getattr(win32.EventMonitor, "_jarvis_ime_shim", False) is True


def test_ensure_drifted_reinstalls() -> None:
    _clear_shim_flags()
    win32.EventMonitor._jarvis_ime_shim = True
    win32.EventMonitor._jarvis_ime_drift = True
    assert ime_shim.ensure() == "installed"
    assert getattr(win32.EventMonitor, "_jarvis_ime_drift", False) is False


def test_ensure_installed_is_noop() -> None:
    """installed: ensure() does not replace run (idempotent), status stays installed."""
    assert ime_shim.install() is True
    patched = win32.EventMonitor.run
    assert ime_shim.ensure() == "installed"
    assert win32.EventMonitor.run is patched
