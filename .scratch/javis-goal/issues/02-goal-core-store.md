# 02 — goals 核心：存储 + 状态机 + prompt + 触发判定

**What to build:** 新 `src/goals.py`（纯逻辑模块，不 import 任何前端）：goals.json 存储、四态状态机、goal_id 乐观版本、`should_continue` 纯函数判定、双 prompt 渲染；`jarvis.json` `goals.max_turns` 预算覆盖。

**Blocked by:** —（可与 01 并行）

**Status:** done

## 背景

- goal 状态机与续跑触发判定全为纯逻辑，必须可脱离 TUI/GUI/CLI 单测。

## 范围

- [ ] 存储：`~/.jarvis/goals.json`（JARVIS_HOME 可覆盖），顶层 dict 按 thread_id 键，原子写 tmp+rename
- [ ] 记录 shape：`{thread_id, goal_id, objective, status, turns_used, max_turns, completed_at?, audit_evidence?}`
- [ ] 状态机：goal_set / goal_pause / goal_resume / goal_clear / goal_status；complete/budget_limited 终态；goal_id 每次 set +1，乐观版本，stale 写显式失败
- [ ] `should_continue(goal, turn_outcome, ctx)` 纯函数：active && turns_used<max && tool_calls>0 && 非 Plan && 无悬挂 interrupt && 非 sched-*
- [ ] `continuation_prompt` / `budget_prompt` 渲染（移植 codex continuation.md / budget_limit.md 纪律）
- [ ] `jarvis.json` `goals.max_turns`（默认 5）
- [ ] tests/test_goals.py：状态机全迁移 / 版本冲突 / should_continue 真值表 / prompt 渲染 / 原子写（自建目录纪律，禁 tmp_path）

## 非目标

- 不做模型工具注入（票 04）、不做命令 dispatch（票 03）、不做前端触发（票 05/06）
