# tui-ux19 headless pilot: CopyableRichLog 工具条目双变体 + 点击展开/收起
import asyncio
import textual.events as events
from textual.app import App, ComposeResult
from textual.containers import Container

from src.tui_log import CopyableRichLog
from src.tui_format import (
    format_tool_call,
    tool_detail_block,
    tool_detail_worth_expanding,
)

PASS = []
FAIL = []


def check(name, cond, info=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name} {info}")


class ProbeApp(App):
    def compose(self) -> ComposeResult:
        with Container(id="box"):
            yield CopyableRichLog(
                id="messages", wrap=True, markup=True, auto_scroll=True
            )

    def on_mount(self):
        self.rlog = self.query_one(CopyableRichLog)
        self.rlog.hint = None
        # on_show（布局落定、_size_known=True）是异步投递，延迟 0.2s 确保先落定
        self.set_timer(0.2, self._run)

    def _click(self, log, up_x, up_y, chain, dx, dy):
        """模拟真实 Textual 点击语义：MouseDown 于 (up_x-dx, up_y-dy)，MouseUp/Click 于 (up_x, up_y)。"""
        md = events.MouseDown(
            log, x=up_x - dx, y=up_y - dy, delta_x=0, delta_y=0, button=1,
            shift=False, meta=False, ctrl=False,
        )
        log.on_mouse_down(md)
        click = events.Click(
            widget=log, x=up_x, y=up_y, delta_x=dx, delta_y=dy, button=1,
            shift=False, meta=False, ctrl=False, chain=chain,
        )
        log.on_click(click)

    def _run(self):
        log = self.rlog
        collapsed = format_tool_call(
            "read_file",
            args='{"file_path": "/workspace/a.txt", "limit": 42}',
            output="line1",
            detail=True,
        )
        expanded = tool_detail_block(
            "read_file",
            args='{"file_path": "/workspace/a.txt", "limit": 42}',
            output="line1\nline2",
        )
        check("worth=True（有输出）",
              tool_detail_worth_expanding("read_file", "x", output="line1"))
        check("worth=False（短参数无输出）",
              not tool_detail_worth_expanding("ls", "abc"))

        # 1) 折叠态上屏
        log.write_tool_entry(collapsed, expanded)
        text1 = log.plain_text()
        check("折叠态：详情标记行在 plain_text", "＋ 详情（点击展开/收起）" in text1, repr(text1))
        check("折叠态：无 [dim] 原文泄漏", "[dim]" not in text1 and "[/dim]" not in text1, repr(text1))
        check("折叠态：展开内容未上屏", "line2" not in text1, repr(text1))
        check("注册了 1 个条目", len(log._tool_entries) == 1, f"entries={len(log._tool_entries)}")

        # 2) 单点击命中标记行 → 展开
        entry = log._tool_entries[0]
        target_row = entry["end"] - 1
        self._click(log, 5, target_row, 1, 0, 0)
        text2 = log.plain_text()
        check("单点击 → 展开态上屏（输出 line2 可见）", "line2" in text2, repr(text2))
        check("展开态：收起标记在 plain_text", "＋ 收起（点击收起）" in text2, repr(text2))
        check("条目 active 翻转", log._tool_entries[0]["active"] is True)

        # 3) 拖选（按下(2,row) → 抬起(5,row)，|dx|=3）不触发
        entry = log._tool_entries[0]
        target_row = entry["end"] - 1
        self._click(log, 5, target_row, 1, 3, 0)
        check("拖选 ≥2 cell → 不收起", log._tool_entries[0]["active"] is True)

        # 4) 双击 chain=2 不触发
        self._click(log, 5, target_row, 2, 0, 0)
        check("chain=2 → 不切换", log._tool_entries[0]["active"] is True)

        # 5) 再次单点击 → 收起
        entry = log._tool_entries[0]
        self._click(log, 5, entry["start"], 1, 0, 0)
        text3 = log.plain_text()
        check("再单点击 → 收起回折叠态", "line2" not in text3, repr(text3))
        check("收起后 active=False", log._tool_entries[0]["active"] is False)

        # 6) 多条目：展开第一条后，后续条目 start/end 同步位移
        c2 = format_tool_call("grep", args="query=" + "q" * 90, detail=True)
        e2 = tool_detail_block("grep", args="query=" + "q" * 90, output="hit")
        log.write_tool_entry(c2, e2)
        self._click(log, 5, log._tool_entries[0]["start"], 1, 0, 0)  # 展开第一条
        later = log._tool_entries[1]
        ok = (
            later["start"] < len(log.lines)
            and later["end"] <= len(log.lines)
            and bool(log.lines[later["start"]:later["end"]])
        )
        check("第二条目坐标在展开后仍指向合法行", ok,
              f"start={later['start']} end={later['end']} lines={len(log.lines)}")

        # 7) clear 复位
        log.clear()
        check("clear 后条目清空", len(log._tool_entries) == 0)
        check("clear 后 plain_text 为空", log.plain_text() == "", repr(log.plain_text()))

        print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
        if FAIL:
            self.exit()


async def main():
    app = ProbeApp()
    async with app.run_test(size=(100, 40)):
        await asyncio.sleep(1.0)
    print("headless driver closed")


if __name__ == "__main__":
    asyncio.run(main())
