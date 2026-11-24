# 05 — TUI 自动续跑（核心）

**What to build:** TUI 回合 finalize 后调 `should_continue` 触发续跑回合：续跑输入经 tui-ux7 回合门 + FIFO 排队；零工具调用 / cancel / 预算耗尽 / complete / Plan 各语义齐备；状态行与 [GOAL] 标记。

**Blocked by:** 01, 04

**Status:** done

## 背景

- 自动续跑链是 goal 功能的核心行为，TUI 为主前端；排队先例 = tui-ux7 回合门 / FIFO（`_turn_gate_threads` / `_queued_messages` / `_release_turn_gate`）。

## 范围

- [ ] tui_turn.py `TurnPresenter` finalize 后调 `should_continue(goal, TurnOutcome, ctx)`；触发则续跑输入（continuation_prompt）经回合门排队
- [ ] 零工具调用（tool_calls_count=0）→ 不续跑（防转圈）
- [ ] outcome=cancel（Esc drain）→ 该回合不续跑，goal 保持 active（断链非暂停）
- [ ] outcome=abandon → 不续跑
- [ ] turns_used==max_turns → 该轮携 budget_prompt 收尾交接 → 后置 budget_limited（终态）
- [ ] complete_goal 成功 → 续跑链断开
- [ ] Plan 模式 → 不续跑（Plan 门先于续跑）
- [ ] 续跑回合状态行「目标续跑 N/M」；header sub_title `[GOAL]` 标记（/sessions 切换联动）
- [ ] TUI 测试（offscreen 先例 tui-ux12/14）：触发 / 排队 / 各场景断言
- [ ] 正交回归：test_permissions / test_vault_guard / test_resilience / test_plan_mode 零改全绿

## 非目标

- 不做 GUI/CLI 移植（票 06）
