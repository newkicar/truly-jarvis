# 03: tests/test_tui_log.py + 回归 + 提交

**What to build:**
- 新 `tests/test_tui_log.py`（@pytest.mark.asyncio，JarvisApp+FakeAgent+run_test 先例 test_tui.py）：
  1 贴底 write 自动跟随；2 上翻后 write 不跳+pending+1+hint -active+文案含 N；
  3 多写 N 累加；4 空白写不计数；5 点击 #jump_hint → 贴底+hint 消失+再写恢复跟随；
  6 手动滚回底部 hint 自动隐藏；7 clear() 复位。
  滚动驱动：`log.scroll_y = 0`（reactive 设值）/ `log.scroll_end()`；hint 注入 on_mount 后生效。
- 回归：& D:\python_env\python.exe -m pytest tests/test_tui_log.py tests/test_tui.py tests/test_tui_modals.py tests/test_tui_turn_gate.py -q
  （全绿；预存 test_config×3 忽略；本批不引入 tmp_path）。
- AGENTS.md 追加「TUI 体验十六」条目；提交（中文 conventional）：
  feat(tui-ux16): 对话区粘底滚动——上翻停跟随 +「↓ N 条新消息」可点击提示 + 点击/滚底恢复跟随（codex 交互模型，Textual widget 层自研）
  （只 add 具体路径，禁止 -A；不 push）。

**Blocked by:** 01, 02。

**Status:** done

- [ ] 7 用例全绿
- [ ] 4 个 TUI 套件回归无新增失败
- [ ] AGENTS.md 条目 + 本地 commit（不 push）
