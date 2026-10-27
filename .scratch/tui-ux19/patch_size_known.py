# -*- coding: utf-8 -*-
p = "src/tui_log.py"
raw = open(p, "rb").read().decode("utf-8")
a1 = "        self._tool_entries: list[dict] = []\r\n        self._click_down: tuple[int, int] | None = None\r\n"
assert a1 in raw, "anchor1"
add1 = "        self._size_known = False  # tui-ux19: 首次 on_show（布局落定）后置 True，工具条目双变体才可预渲染\r\n"
raw = raw.replace(a1, a1 + add1, 1)
a2 = "    def focus_on_click(self) -> bool:"
assert a2 in raw, "anchor2"
on_show = (
    "    def on_show(self, event: events.Show) -> None:\r\n"
    "        \"\"\"tui-ux19: widget 首次上屏（父布局已完成，size.width 有效）→ 工具条目双变体预渲染可用。\"\"\"\r\n"
    "        self._size_known = True\r\n"
    "\r\n"
)
raw = raw.replace(a2, on_show + a2, 1)
open(p, "wb").write(raw.encode("utf-8"))
import ast
ast.parse(raw)
print("patched + ast OK")
