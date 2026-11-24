# 01 — TurnOutcome 结构体（prefactor）

**What to build:** 新增 `TurnOutcome` dataclass，让自动续跑触发能读到「本回合 tool_calls 数 + outcome」；`run_agent_turn` 返回值迁移，`.ok` 保 legacy bool 语义，5 个调用点迁移，行为不变。

**Blocked by:** —（可与 02 并行）

**Status:** done

## 背景

- 自动续跑需要「回合收尾 outcome + 零工具调用判定」；现在 `run_agent_turn` 返回 legacy bool，outcome 值只存在于 streaming 内部。

## 范围

- [ ] `TurnOutcome(ok: bool, outcome: str, tool_calls_count: int, last_usage: dict | None)`（放新模块或 streaming.py）
- [ ] outcome 值对齐现有：complete / abandon / cancel
- [ ] 迁移 5 调用点：main.py ×2、tui_turn.py ×1、gui/runtime.py ×2（行号以当前 HEAD 为准）
- [ ] 读 legacy bool 的调用点改读 `.ok`，无 legacy 直读残留
- [ ] 全量回归零新增失败（排除预存 test_config×3）

## 非目标

- 不动 handoff / finalize / cancel drain 语义
