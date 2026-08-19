# Spec: JARVIS 后续路线（Inbox 边界 → TUI 体验 → 测试质量）

`Status: done`

> 来源：`/grill-with-docs` 会话（2026-08-18）。领域术语见仓库根 `CONTEXT.md`。

## 目标

按顺序交付三阶段能力：

1. **Inbox 唯一写入口 + 项目内快照回退**（Vault 其它文件夹只读；归档由人在 Obsidian 完成）
2. **TUI 体验增强**（流式 Markdown → 权限 diff → `@` 补全 → 侧边栏）
3. **测试与冒烟**（假 agent 单测进 CI；真模型 TUI 冒烟保持手动）

## 已确认的边界

- JARVIS **不归档**；`Inbox/` 已加入 vault `.gitignore`（远端需用户手动 `git add -f .gitignore`）
- Inbox 快照存 **JARVIS 项目**，写入时自动记录，带 `thread_id` + 检查点
- 会话 `/rollback` 只还原该会话写过的 Inbox 文件，列出路径，可覆盖 Obsidian 手改；不动定时任务写入
- Inbox 内可改删（需审批）；Inbox 外即使 HITL 放行也拒绝

## 票序

见 `issues/` 01–11，按 Blocked by 依赖顺序实施。
