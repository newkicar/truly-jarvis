# 02: tui.py hint Button + CSS + 装配（src/tui.py）

**What to build:**
- compose：`#chat_stack` 内 `yield Static("", id="ai_stream")` 后追加
  `yield Button("↓ 有新消息", id="jump_hint")`。
- CSS（`#ai_stream.-active` 块后）：
  `#jump_hint { display: none; width: 100%; margin: 0; }` + `#jump_hint.-active { display: block; }`。
- on_mount：`log.hint = self.query_one("#jump_hint", Button)`（try/except NoMatches → None）。
- 新增 `JarvisApp.on_button_pressed(event)`：id == "jump_hint" →
  `self.query_one("#messages", RichLog).jump_to_end()`（NoMatches 守卫；其它按钮忽略）。

**Blocked by:** 01。

**Status:** done

- [ ] compose/CSS/on_mount/dispatch 四处落点
- [ ] display:none 时不进焦点链（Tab 不经过隐藏 hint）
- [ ] 其它 modal 按钮事件不受影响（按 id 分发）
