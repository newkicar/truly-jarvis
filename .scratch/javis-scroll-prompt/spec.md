# spec: TUI 对话区粘底滚动（tui-ux16）

## 需求（用户原话）
LLM 输出上屏时对话窗口总跳到最新消息，翻看旧消息总被打断。参考 codex 的开源方案：
不自动跳转，只在对话窗口显示一个可点击提示，用户点击提示才跳转到最新消息；
屏幕跟随最后一条消息时自动滚动，用户翻看前面消息时屏幕不自动滚动。

## 外部参考（先查现成解法）
- **codex-rs（rust 终端 UI）**：`chat` widget 带 sticky-follow 语义——消息追加时若用户停在底部则跟随，
  一旦用户上翻即解除跟随并显示「N 条新消息」提示，点击/滚回底部恢复跟随。本项目在 Textual
  widget 层复刻同一交互模型。
- **Textual 原生**：`RichLog.auto_scroll` 只是全局布尔（8.2.8 实证），无 sticky 语义、无逐写控制；
  `RichLog.write` 支持逐写 `scroll_end: bool | None` 覆盖（None=用 auto_scroll）。
  → 无现成组件，UI 层自研合理。
- **deepagents / langchain**：无 UI 层方案（框架不管渲染），不在此层寻找解法。

## Textual 8.2.8 实证（D:\python_env）
1. `RichLog.write(content, width, expand, shrink, scroll_end=None, animate)`：
   `auto_scroll = self.auto_scroll if scroll_end is None else scroll_end`，可逐写覆盖。
2. 尺寸未知时写入进 `_deferred_renders`（`DeferredRender(content, width, expand, shrink, scroll_end)`），
   `on_resize` 补放用 `self.write(*deferred_render)` —— **位置参数**回放，第 5 个位置（args 下标 3）
   = scroll_end；显式判定须 `len(args) >= 4 or "scroll_end" in kwargs`。
3. 滚动偏移 = reactive `scroll_x`/`scroll_y`（float）；`max_scroll_y` 是 Widget property；
   `is_vertical_scroll_end` 无容差 → 自写 `_at_bottom(tol=2)`。
4. 统一滚动变化钩子 = `watch_scroll_y(old_value, new_value)`（滚轮/键盘/滚动条/程序 scroll_to/end
   全走这里）——wheel 无公开 handler（私有 `_on_mouse_scroll_down`），不碰事件层。
5. `Button` 8.2.8 无 `markup` 参数；hint 文案无 `[]`，markup 解析安全。
6. 本地 `CopyableRichLog`（src/tui_log.py）已 override write/clear/render_line；
   `#ai_stream` 是独立 Static（流式期间原地 update，不写 log）→ pending 计数不受流式影响。
   log 写点全在 UI 线程（call_from_thread 或 dispatch）。

## 设计定案
### CopyableRichLog（src/tui_log.py）
- 状态：`self._pending_msgs: int = 0`、`self.hint: Button | None = None`（tui.py on_mount 注入，NoMatches 兜 None）。
- `_at_bottom(tol=2)`：`max_scroll_y` 为 0 → True；否则 `scroll_offset.y >= max(0, max_scroll_y - tol)`。
- override `write`：无显式 scroll_end（kwargs 无 且 位置 args 不足 4）时——
  贴底 → `kwargs["scroll_end"]=True`（自动跟随，pending=0、hint 隐藏）；
  上翻 → `kwargs["scroll_end"]=False` 写入、`content not in ("", None)` 时 `_pending_msgs += 1`
  （空白写 `""` 不计数；deferred 期写入走原路不计数、on_resize 回放时 y==0 自然恢复跟随）、刷新 hint。
- override `watch_scroll_y`：super() 后——贴底 → `_pending_msgs=0`；`_refresh_hint()`
  （pending>0 且非贴底 → 显示「↓ N 条新消息」；否则隐藏）。
- `jump_to_end()`：`_pending_msgs=0`、hint 隐藏、`scroll_end(animate=False, immediate=True, x_axis=False)`。
- override `clear`：super 前后 `_pending_msgs=0` + hint 隐藏（y 复位 0 亦触发 watch，幂等）。
- hint 显隐走 CSS 类：`#jump_hint { display:none } #jump_hint.-active { display:block }`
  + `add_class/remove_class`（`#ai_stream`/`#todo_panel` 先例；勿与 widget.visible 互搏）。
- 线程：全部 UI 线程（watch/write/click 同线程；pending 计数单线程无锁）。

### JarvisApp（src/tui.py）
- compose：`#chat_stack` 内 `#ai_stream` 之后 `yield Button("↓ 有新消息", id="jump_hint")`。
- CSS（`#ai_stream.-active` 块后）：`#jump_hint { display:none; width:100%; } #jump_hint.-active { display:block; }`。
- on_mount：`log.hint = self.query_one("#jump_hint", Button)`（NoMatches → None）。
- 新增 `JarvisApp.on_button_pressed`：`event.button.id == "jump_hint"` → `log.jump_to_end()`（NoMatches 守卫）。
  modal 自带 handler 优先消费，无冲突；其它按钮 id 一律忽略。

### 语义边界
- 计数单位 = 非空 `write()` 调用（一次 AI 回复 = header+markdown 两写计 2，用户消息 1 写计 1；
  设计取舍：稳定、无需跨调用聚合；提示文案「N 条新消息」的 N 即 pending 计数）。
- `log.clear()`（/clear、/replay、/history 重放）复位。
- 流式 `#ai_stream` 静态区更新不计数、不滚动（finalize 时一次写 log 才计 1）。

## 验收
1. 贴底时新消息上屏自动跟随（现状保持）。
2. 上翻后新消息上屏：窗口不动、hint 出现「↓ N 条新消息」且 N 累加。
3. 点击 hint：跳底 + hint 消失 + 恢复自动跟随。
4. 手动滚回底部：hint 自动消失。
5. `log.clear()` 复位 pending/hint。
6. 测试：新 `tests/test_tui_log.py`（7–8 用例）+ `tests/test_tui.py`
   `tests/test_tui_modals.py` `tests/test_tui_turn_gate.py` 全绿（预存 test_config×3 忽略）。
7. 提交 `feat(tui-ux16): …`（本地 commit，不 push——用户网络约定）；AGENTS.md 追加「TUI 体验十六」条目。
