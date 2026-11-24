# 06 — GUI + CLI 续跑与 goal 状态展示

**What to build:** GUI（per-tid gate + UiBridge）与 CLI headless（直接续跑循环）移植 TUI 自动续跑；GUI 状态栏与 CLI headless 显示 goal 状态。

**Blocked by:** 05

**Status:** done

## 背景

- 续跑与展示需三前端等价；GUI 先例 = gui-ux22 的 per-tid gate + UiBridge。

## 范围

- [ ] GUI：gui/runtime.py 两处 run_agent_turn 调用点 finalize 后调 should_continue；续跑输入经 per-tid gate + UiBridge 排队
- [ ] GUI 状态栏：goal 状态（objective + 状态 + N/M，[GOAL] 等价）
- [ ] CLI headless：run_agent_turn finalize 后同判定续跑循环（零工具调用 / cancel / 预算 / complete 语义同 TUI）
- [ ] CLI headless goal 状态行显示
- [ ] 不做 GUI/CLI 特有 prompt（复用 goals.py 双 prompt）
- [ ] GUI offscreen harness（gui_fakes 先例）：续跑 + 状态栏断言

## 非目标

- 不新增前端命令（/goal 已由票 03 三前端共享）
