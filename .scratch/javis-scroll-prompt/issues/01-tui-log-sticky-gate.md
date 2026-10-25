# 01: CopyableRichLog 粘底门控 + watch_scroll_y + hint 计数（src/tui_log.py）

**What to build:**
- `__init__` 增 `self._pending_msgs: int = 0`、`self.hint: Button | None = None`（import Button）。
- `_at_bottom(tol=2)`：max_scroll_y 为 0 → True；否则 scroll_offset.y >= max(0, max_scroll_y - tol)。
- override `write`：无显式 scroll_end（`"scroll_end" not in kwargs` 且 `len(args) < 4`）时：
  贴底 → kwargs["scroll_end"]=True；上翻 → kwargs["scroll_end"]=False 且
  content not in ("", None) → _pending_msgs += 1 + _refresh_hint()。位置显式（args 下标 3）原样尊重。
- override `watch_scroll_y(old, new)`：super() 后——贴底 → pending=0；_refresh_hint()。
- `_refresh_hint/_show_hint/_hide_hint`：hint 为 None no-op；显示文案 f"↓ {pending} 条新消息" + add_class("-active")。
- `jump_to_end()`：pending=0、hint 隐藏、scroll_end(animate=False, immediate=True, x_axis=False)。
- override `clear`：_plain_lines.clear + pending=0 + hint 隐藏（super 前，幂等）。

**Blocked by:** 无（基础件）。

**Status:** done

- [ ] 贴底 write 自动跟随、pending 恒 0、hint 隐藏
- [ ] 上翻 write 不滚动、pending 按非空写累加、hint 显示 N
- [ ] 空白写（""/None）不计数
- [ ] 位置参数显式 scroll_end（deferred 回放形态）不被覆盖
- [ ] watch_scroll_y 贴底清 pending、上翻显示 hint
- [ ] jump_to_end / clear 复位语义正确
