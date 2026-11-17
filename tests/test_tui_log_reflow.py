"""tui-ux20 宽度自适应换行（reflow）单测：Resize → 全量重折 + 块注册表 + 预布局 FIFO。

自建目录纪律：不用 tmp_path（本机 pytest 基 temp 目录 WinError 5 中毒），纯内存。
复用 tests.test_tui_log._new_app 启动方式（run_test(size=...)）。
断言纪律：只断行数增减方向 / max_scroll_x==0 / virtual_size.width<=size.width，
不断精确宽度（滚条槽随主题/尺寸浮动）。
"""
import pytest

from src.tui_log import CopyableRichLog
from tests.test_tui_log import _new_app


@pytest.mark.asyncio
async def test_widen_reflows_fewer_lines():
    """加宽 80->110：按新内容区宽全量重折，行数减少，水平溢出消失。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log.write("word " * 60)
        log.write_tool_entry("tool" * 20, "expand" * 50)
        await pilot.pause()
        before = len(log.lines)
        await pilot.resize_terminal(110, 24)
        after = len(log.lines)
        assert after < before, (
            "width 80->110 should reflow to fewer lines, %d -> %d" % (before, after)
        )
        assert log.max_scroll_x == 0
        assert log.virtual_size.width <= log.size.width


@pytest.mark.asyncio
async def test_narrow_reflows_more_lines():
    """收窄 120->80：行数增多（reflow 双向生效，非只增不减的棘轮）。"""
    app = _new_app()
    async with app.run_test(size=(120, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log.write("z" * 400)
        await pilot.pause()
        before = len(log.lines)
        await pilot.resize_terminal(80, 24)
        after = len(log.lines)
        assert after > before, (
            "width 120->80 should reflow to more lines, %d -> %d" % (before, after)
        )
        assert log.max_scroll_x == 0


@pytest.mark.asyncio
async def test_reflow_then_toggle_tool_entry():
    """重折后工具条目块注册表仍有效：点击展开、再点收起（marker 与既有测试同式）。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log.write("header")
        log.write_tool_entry("collapsed-tool", "expanded-detail" * 10)
        await pilot.pause()
        entry = log._tool_entries[0]  # noqa: SLF001 共享 dict，reflow 后仍有效
        await pilot.resize_terminal(110, 24)
        marker_y_rel = entry["end"] - 1 - int(log.scroll_offset.y)
        assert marker_y_rel >= 0
        ok = await pilot.click(log, offset=(1, marker_y_rel))
        assert ok
        await pilot.pause()
        assert entry["active"] is True
        expanded_lines = len(log.lines)
        log.scroll_end(animate=False, immediate=True, x_axis=False)
        await pilot.pause()
        marker_y_rel = entry["end"] - 1 - int(log.scroll_offset.y)
        ok = await pilot.click(log, offset=(1, marker_y_rel))
        assert ok
        await pilot.pause()
        assert entry["active"] is False
        assert len(log.lines) < expanded_lines


@pytest.mark.asyncio
async def test_height_only_resize_no_reflow():
    """仅高度变化（宽度不变）：不触发重折，_reflow_width 与行数均保持不变。"""
    app = _new_app()
    async with app.run_test(size=(110, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log.write("line-" * 100)
        await pilot.pause()
        # 先一次宽度变化确立 _reflow_width（reflow 记账基线）
        await pilot.resize_terminal(120, 24)
        await pilot.pause()
        reflow_width_before = log._reflow_width  # noqa: SLF001
        lines_before = len(log.lines)
        assert reflow_width_before > 0
        # 仅高度变化：guard 比 widget 宽，不重折
        await pilot.resize_terminal(120, 30)
        await pilot.pause()
        assert log._reflow_width == reflow_width_before  # noqa: SLF001
        assert len(log.lines) == lines_before


@pytest.mark.asyncio
async def test_pre_layout_fifo_drain():
    """预布局（size 未定）写入入 FIFO：native write 与工具条目按入队顺序 drain，序位正确。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log._size_known = False  # noqa: SLF001 强制预布局路径
        log.write("early native")
        log.write_tool_entry("early tool", "early detail")
        log.write("mid native")
        assert len(log._pending_writes) == 3  # noqa: SLF001
        entry = log._tool_entries[0]  # noqa: SLF001
        assert entry["start"] == 0
        assert entry["end"] == 0
        assert entry["pending"] == ("early tool", "early detail")
        log.on_show(None)  # noqa: SLF001 drain + materialize
        await pilot.pause()
        assert log._pending_writes == []  # noqa: SLF001
        entry = log._tool_entries[0]  # noqa: SLF001
        assert entry["strips"] is not None
        assert entry["pending"] is None
        text = log.plain_text()
        assert text.find("early native") < text.find("early tool") < text.find("mid native")


@pytest.mark.asyncio
async def test_max_lines_skips_block_registry():
    """max_lines 变体：设值后块注册表停止注册新块（设值前启动期注册的 native 块保留、无害），
    工具条目全旁路，resize 亦不重折不注册。"""
    app = _new_app()
    async with app.run_test(size=(80, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        log.max_lines = 5
        before = len(log._items)  # noqa: SLF001 启动写入（max_lines=None 期）已注册的 native 块
        log.write("x")
        log.write_tool_entry("c", "e")
        await pilot.pause()
        assert len(log._items) == before  # noqa: SLF001 设 max_lines 后不再注册新块
        assert log._tool_entries == []  # noqa: SLF001
        await pilot.resize_terminal(110, 24)
        assert len(log._items) == before  # noqa: SLF001 resize 不重折不注册
        assert log._tool_entries == []  # noqa: SLF001


@pytest.mark.asyncio
async def test_reflow_preserves_scroll_position():
    """上翻（停跟随）后重折保持 scroll y（仅钳制到 max_scroll_y），不强制回底。"""
    app = _new_app()
    async with app.run_test(size=(110, 24)) as pilot:
        log = pilot.app.query_one("#messages", CopyableRichLog)
        await pilot.pause()
        for i in range(30):
            log.write("line %d" % i)
            await pilot.pause()
        assert log._at_bottom()  # noqa: SLF001
        log.scroll_to(0, 0, animate=False, immediate=True)
        await pilot.pause()
        assert not log._at_bottom()  # noqa: SLF001
        await pilot.resize_terminal(120, 24)
        assert int(log.scroll_offset.y) == 0
