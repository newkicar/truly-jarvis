# Spec: Esc 三段缓冲 + Ctrl+C 二次确认退出（tui-ux15）

背景：运行中一次 Esc 即取消整轮 agent（drain 语义）；Ctrl+C 一次即退出终端。
对标 Codex 习惯引入缓冲：

## 1. Esc 三段（运行中）
- Esc#1（worker 活跃）：prime 取消——notify「再按一次 Esc（1.5s 内）取消本轮」，不取消。
- Esc#2（1.5s 内）：执行既有取消体（hide_ai_stream / bump HITL / 日志「（已取消）」/ banner /
  worker.cancel() / pop），drain 语义不变；随后 prime 撤回：notify「已取消；再按一次 Esc（1.5s 内）可撤回上一轮」。
- Esc#3（下一个 1.5s 内）：_trigger_implicit_undo() 撤回 1 轮（原则与现状一致；turn gate 未释放时保留 prime，门开后单 Esc 即撤回）。
- 空闲态：现有「双 Esc 撤回」语义完全不变。
- /sessions 切换会话（_adopt_thread）清零三段状态。

## 2. Ctrl+C 二次确认
- 首次 Ctrl+C：notify「再按一次 Ctrl+C（1.5s 内）退出 JARVIS；单次不退出」，不退出。
- 窗口内第二次：退出（Textual 内置 action_quit，与 Ctrl+Q 同一收尾路径）。
- 窗口过期重新 prime。Ctrl+Q 保持即时退出不变。

## 不变量
- 取消 drain 语义（RunControl.request_drain("user-cancel") → GraphDrained 不进韧性重试、finally finalize_turn）零改动；
  本条只改「何时触发取消/撤回/退出」。
- 帮助文案同步：commands.py TUI_HELP 退出行。

## 验收
- tests/test_tui.py：运行中单 Esc 不取消；Esc×2 取消；取消后 Esc 第 3 次撤回；
  空闲双 Esc 回归；Ctrl+C 单按不退出 / 双按退出 / 过期重 prime。
