# 02 Ctrl+C 二次确认退出

**Status:** done（2026-10-25 实现 + 测试全绿）

实现（src/tui.py）：
- BINDINGS：Binding("ctrl+c","quit","退出",priority=True) → action 改 "prime_quit"（priority=True 保留）。
- __init__ 增 self._quit_primed_at = 0.0。
- 新增 action_prime_quit()：窗口内二次 → 清零并 self.action_quit()；否则 prime + notify。
- _adopt_thread 顶部清零 _quit_primed_at。

文案同步（src/commands.py）：
- TUI_HELP 退出行：「退出：Ctrl+Q 立即退出；Ctrl+C 需 1.5s 内按两次（单次不退出）；
  Esc 三段：prime 取消 → 取消 → 撤回（空闲态双 Esc 撤回不变）」

测试（tests/test_tui.py）：
- 单按 prime_quit 不退出（is_running True、notify）；窗口内双按退出（is_running False）；
  过期重 prime 不退出。
