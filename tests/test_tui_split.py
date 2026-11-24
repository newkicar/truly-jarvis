"""tui-ux22 01:resolve_panes 纯 helper 四态矩阵测试(纯 dict 造态,不碰 UI)。

纪律:无 tmp_path / tempfile.mkdtemp(WinError 5 中毒);
state 一律纯 dict + permissions.side_open/side_close 造态。
"""
import dataclasses

import pytest

from src.permissions import side_close, side_open
from src.tui import PaneLayout, resolve_panes


def _state() -> dict:
    return {"tools": {}}


# ---- 1. 无 side -------------------------------------------------------------


def test_no_side_focus_forced_main():
    lay = resolve_panes(_state(), "main-1")
    assert lay.side_tid is None
    assert lay.side_parent is None
    assert lay.on_side is False
    assert lay.focus == "main"
    assert lay.mainline_tid == "main-1"
    assert lay.pane_of("main-1") == "main"


def test_no_side_explicit_side_focus_forced_main():
    lay = resolve_panes(_state(), "main-1", focus="side")
    assert lay.focus == "main"  # 无 side:右 pane 不存在,焦点落主


def test_empty_active_tid_defensive():
    lay = resolve_panes(_state(), "")
    assert lay.side_tid is None
    assert lay.on_side is False
    assert lay.focus == "main"
    assert lay.pane_of("x") == "main"


def test_none_state_defensive():
    lay = resolve_panes(None, "main-1")
    assert lay.side_tid is None
    assert lay.focus == "main"


# ---- 2. 有 side + 焦点左 ----------------------------------------------------


def test_side_present_active_main_focus_left():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "main-1")
    assert lay.side_tid == "side-a"
    assert lay.side_parent == "main-1"
    assert lay.on_side is False
    assert lay.focus == "main"
    assert lay.pane_of("side-a") == "side"
    assert lay.pane_of("main-1") == "main"
    assert lay.pane_of("other") == "main"
    assert lay.pane_of("") == "main"


def test_side_present_explicit_focus_main_kept():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "main-1", focus="main")
    assert lay.focus == "main"
    assert lay.side_tid == "side-a"


# ---- 3. 有 side + 焦点右 ----------------------------------------------------


def test_side_present_explicit_focus_side():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "main-1", focus="side")
    assert lay.focus == "side"
    assert lay.side_tid == "side-a"
    assert lay.mainline_tid == "main-1"


def test_active_side_derives_focus_side():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "side-a")
    assert lay.on_side is True
    assert lay.mainline_tid == "main-1"
    assert lay.side_tid == "side-a"
    assert lay.side_parent == "main-1"
    assert lay.focus == "side"
    assert lay.pane_of("side-a") == "side"
    assert lay.pane_of("main-1") == "main"


def test_active_side_explicit_focus_main_kept():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "side-a", focus="main")
    assert lay.focus == "main"
    assert lay.on_side is True


# ---- 4. 不一致态:孤儿 side / 缺键 / 缺 parent ------------------------------


def test_orphan_side_not_reported_as_current():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "main-2")
    assert lay.side_tid is None  # 孤儿 side 挂在 main-1 下,不纠正
    assert lay.on_side is False
    assert lay.focus == "main"


def test_side_parent_missing_defensive():
    st = _state()
    # 手工造:side 登记在集合里但 parent 映射缺失(旧引用防御)
    from src.permissions import SIDE_THREADS_KEY

    st.setdefault(SIDE_THREADS_KEY, set()).add("side-a")
    lay = resolve_panes(st, "side-a")
    assert lay.on_side is True
    assert lay.mainline_tid == "side-a"  # parent 缺失:保留自身,只报告不纠正
    assert lay.side_parent is None


def test_side_close_clears():
    st = _state()
    side_open(st, "side-a", "main-1")
    side_close(st, "side-a")
    lay = resolve_panes(st, "main-1")
    assert lay.side_tid is None
    assert lay.focus == "main"


# ---- 契约 ------------------------------------------------------------------


def test_invalid_focus_falls_back_to_main():
    st = _state()
    side_open(st, "side-a", "main-1")
    lay = resolve_panes(st, "main-1", focus="bogus")
    assert lay.focus == "main"


def test_layout_is_frozen_dataclass():
    lay = resolve_panes(_state(), "main-1")
    assert isinstance(lay, PaneLayout)
    assert type(lay).__dataclass_params__.frozen is True  # Python 3.14 is_dataclass 无 frozen 参
    with pytest.raises(dataclasses.FrozenInstanceError):
        lay.focus = "side"
