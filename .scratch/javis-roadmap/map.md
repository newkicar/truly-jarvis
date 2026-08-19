# JARVIS 后续路线 — 决策摘要

`Status: done`（2026-08-19 收尾）

## 三阶段交付

| 阶段 | 票 | 要点 |
|------|-----|------|
| Inbox 边界 | 01–04 | 仅 `/vault/Inbox/` 可写；写入前快照；`/rollback` 还原 Inbox；ADR 0002 |
| TUI 体验 | 05–08 | 流式 Markdown；权限 diff；`@` 补全；可折叠会话侧边栏 |
| 测试质量 | 09–10 | dispatch/HITL 假 agent 单测；`smoke_test --tui-hitl` 手动 HITL 冒烟 |

## 关键决策（grill 确认）

- JARVIS **不归档**；Inbox 外即使 HITL 放行也拒绝
- 快照存 JARVIS 项目 `inbox_snapshots.sqlite`，非 vault git
- 会话 `/rollback` 只还原该 thread 的 Inbox 写入；`sched-*` 不动
- 真模型 TUI 冒烟**不进 CI**；假 agent pytest 可进 CI

## 测试

- 单测：**165**（`pytest tests/`，不含 smoke）
- 手动：`python -m src.smoke_test --tui-hitl`
