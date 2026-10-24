# 01 Esc 三段缓冲（prime → 取消 → 撤回）

**Status:** done（2026-10-25 实现 + 测试全绿）

实现（src/tui.py）：
- ESC_UNDO_WINDOW = 1.5（已有）旁增 QUIT_CONFIRM_WINDOW = 1.5。
- __init__ 增 self._esc_phase = "none" / self._esc_phase_at = 0.0。
- 重写 action_cancel()：
  - worker 活跃且（_esc_phase != "cancel" 或超窗）→ prime：phase="cancel"、notify、return。
  - worker 活跃且窗口内 → 既有取消体（hide_ai_stream / bump_hitl / log「（已取消）」/ _show_cancel_banner() /
    worker.cancel() / pop / return），随后 _esc_phase="none"、_esc_primed_at=now、
    notify「已取消；再按一次 Esc（1.5s 内）可撤回上一轮」。
  - 空闲/收尾（worker 已 pop）：维持现状——1.5s 内二次 Esc → _trigger_implicit_undo()；
    _trigger_implicit_undo 改返回 bool（门占用返回 False 且保留 prime：_esc_primed_at=now）。
- _adopt_thread 顶部清零 _esc_phase / _esc_primed_at / _quit_primed_at。

测试（tests/test_tui.py）：
- 改 test_escape_cancels_streaming：两次 action_cancel() 后断言「已取消」。
- 改 banner 两条：两次连按后同步读 banner（不 yield，CI-flake 纪律）。
- 新增：单 Esc 不取消 / Esc×3 撤回 / 门占用保留 prime。
- 空闲双 Esc 三条旧测试原样回归。
