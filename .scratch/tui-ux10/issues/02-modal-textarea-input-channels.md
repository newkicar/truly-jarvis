# 02 — ModalTextArea 输入通道（OS 剪贴板粘贴 + Ctrl+Shift+Enter 换行 + 焦点灰态消解）

**What to build:** EditParamsModal 多行编辑框的三个输入通道（工单 01 建好的 ModalTextArea）：

- `ModalTextArea.action_paste` 覆盖（widgets/_text_area.py L2661-2667 原生版只读 app.clipboard
  = 仅 app 内复制内容，外部复制永远粘空——PasteInput 同款病因）：
  `run_worker(self._paste_from_os, thread=True, exclusive=True)`（Widget 无 call_from_thread，
  照 PasteInput L88-135 路径；UI 回调 `is_mounted` 守卫）；
  `_paste_from_os`：`text = read_os_clipboard()` 非空 →
  `self.app.call_from_thread` 内 `res = self._replace_via_keyboard(text, *self.selection)` +
  `self.move_cursor(res.end_location)`；空 → 回落原生 app.clipboard 语义
  （`_native_paste`：clipboard 非空同构插入，等价 L2665-2667）。
- widget BINDINGS 补 `Binding("ctrl+shift+v", "paste", "粘贴", show=False)`；
  原生 `ctrl+v`（_text_area.py L387-389 实证绑定 "paste"）同走覆盖路径。
- EditParamsModal 屏级 BINDINGS 加 `Binding("ctrl+shift+enter", "newline", "换行", show=False)`，
  `action_newline`：`ta = self.focused` 是聚焦中的 ModalTextArea 时
  `res = ta._replace_via_keyboard("\n", *ta.selection)` + `ta.move_cursor(res.end_location)`
  （选中态下 = 换行替换选中块，与粘贴语义一致）；非编辑框聚焦 = no-op。
- CSS：`#edit_box` / `#perm_box` / `#prefix_box` 三个 VerticalScroll 全加 `can-focus: no`
  （textual/css/constants.py L68 实证属性存在）——容器不再抢 DOM 首焦点，tui-ux8 焦点族
  结构根因消解。
- 测试（tests/test_tui.py 或 test_tui_modals.py）：
  - ctrl+shift+enter：聚焦 `#param_0` 后 `pilot.press("ctrl+shift+enter")` → `.text` 尾插 `\n`；
  - 粘贴多行：monkeypatch `src.tui.read_os_clipboard` 返回 `"a\nb"` → `pilot.press("ctrl+v")`
    （或 ctrl+shift+v）→ `.text` 变为 `"a\nb"`（pilot.pause 让 worker 跑完；
    探针路径照 PasteInput 粘贴测试先例）；
  - 灰态消解：`ta.focus()` 后 `ta.selection.is_empty` 为 True（TextArea 无 select_on_focus，
    点击聚焦不产生选区——用户症状「点就变灰」的结构性回归锚点）。

**Type:** feature
**Status:** done (2026-10-21, commit f31a0d5)
**Blocked by:** 工单 01（ModalTextArea 类与 `#param_{idx}` 结构）

## 验收
- [x] ctrl+shift+enter 插入 \n 绿
- [x] OS 剪贴板多行粘贴绿（monkeypatch read_os_clipboard）
- [x] 聚焦无选区断言绿（selection.is_empty）
- [x] 锚点回归 + 全量无新增失败

## Comments
改动清单/结果：ModalTextArea.action_paste 覆盖（worker read_os_clipboard 读 OS 剪贴板，空则回落 app.clipboard；_replace_via_keyboard + move_cursor 尊重选区；挂载后无选区=光标处插入）；ctrl+shift+v widget 级 / ctrl+shift+enter 屏级换行退路；三容器 #perm_box/#edit_box/#prefix_box 经 VerticalScroll(can_focus=False) 构造参数不可聚焦。实证修正：Textual 8.2.8 中 can-focus 是伪类选择器，CSS 写 "can-focus: no" 触发解析错误炸掉整个 modal 样式表（本票初版 CSS 回退，改走构造参数，ScrollableContainer L32/108 实证）。新增 4 条测试 + 修 test_edit_params_paste_os_clipboard 语义（空选区=光标处插入，先 select_all 再粘贴=整体替换）。tests/test_tui.py + test_tui_modals.py 64 全绿。
