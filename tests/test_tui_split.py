"""tui-ux22 01:resolve_panes 纯 helper 四态矩阵测试(纯 dict 造态,不碰 UI)。

纪律:无 tmp_path / tempfile.mkdtemp(WinError 5 中毒);
state 一律纯 dict + permissions.side_open/side_close 造态。
"""
import dataclasses

import pytest
from textual.containers import Vertical

from src.permissions import side_close, side_open
from src.tui import JarvisApp, JarvisTextArea, PaneLayout, resolve_panes
from src.tui_log import CopyableRichLog
from tests.test_tui import FakeAgent


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


# ---- 02: 双 pane 布局（离屏 run_test，纯内存，禁 tmp_path）----


def _split_app(st: dict, side: bool = False) -> JarvisApp:
    """fixture：JarvisApp + FakeAgent，thread_id=main-1；side=True 时先 side_open。"""
    if side:
        side_open(st, "side-a", "main-1")
    return JarvisApp(None, FakeAgent(), st, thread_id="main-1")


@pytest.mark.asyncio
async def test_side_pane_hidden_by_default():
    """无 side：#side_pane display:none、无 -active、不占空间。"""
    app = _split_app(_state())
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one("#side_pane", Vertical)
        assert "-active" not in pane.classes
        assert pane.styles.display == "none"
        assert pane.region.width == 0


@pytest.mark.asyncio
async def test_side_pane_active_50_50_geometry():
    """有 side：-active 在位，右 pane 与主列等宽（50/50）。"""
    app = _split_app(_state(), side=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one("#side_pane", Vertical)
        assert "-active" in pane.classes
        main = app.query_one("#content_column")
        assert pane.region.width == main.region.width
        assert pane.region.width > 0


@pytest.mark.asyncio
async def test_pane_widgets_independent_instances():
    """两 pane 的 log/input widget 实例独立（identity 非共享）。"""
    app = _split_app(_state(), side=True)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.query_one("#messages"), CopyableRichLog)
        assert isinstance(app.query_one("#side_messages"), CopyableRichLog)
        assert app.query_one("#messages") is not app.query_one("#side_messages")
        main_in = app.query_one("#input", JarvisTextArea)
        side_in = app.query_one("#side_input", JarvisTextArea)
        assert isinstance(main_in, JarvisTextArea)
        assert isinstance(side_in, JarvisTextArea)
        assert main_in is not side_in


@pytest.mark.asyncio
async def test_open_close_focus_routing():
    """side_open → 命令结果路由焦点到 #side_input；side_close → 焦点回 #input。"""
    st = _state()
    app = _split_app(st)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        pane = app.query_one("#side_pane", Vertical)
        assert "-active" not in pane.classes
        side_open(st, "side-a", "main-1")
        app._apply_command_result("已开 side 会话 side-a", "side-a")
        await pilot.pause()
        assert "-active" in pane.classes
        assert app.focused is app.query_one("#side_input", JarvisTextArea)
        side_close(st, "side-a")
        app._apply_command_result("已返回主线 main-1", "main-1")
        await pilot.pause()
        assert "-active" not in pane.classes
        assert app.focused is app.query_one("#input", JarvisTextArea)
