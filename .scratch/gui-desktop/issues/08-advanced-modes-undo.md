# 08 — 高级模式与撤回（Plan/Act · YOLO · /undo）

**What to build:** 小白界面里保留但不默认展开的高级能力（spec「高级模式默认收起」）：Plan/Act 双模式切换（Plan 下写/改工具被拦、引导先规划，模式存 permission_state 零重建）；YOLO 线程级免审批开关（`/yolo on|off` 对应 GUI 开关，状态位 [YOLO] 镜像，共享 permission_state live 生效，正交于 VaultWriteGuard 等地板）；撤回上一轮（GUI 变体：撤回按钮 + 快捷键，语义 = TUI 双 Esc 等价，纯消息层 `commands.undo`，悬挂 HITL 随回退作废）。三者入口收在「高级」菜单/状态区，不占主界面。

**Blocked by:** 04（HITL 审批卡片）、05（会话侧栏与命名）

**Status:** done（2026-10-26）

- [ ] Plan 模式：写/改工具被拦并提示先规划；切回 Act 恢复（零 agent 重建）
- [ ] YOLO on：该 thread 审批卡不再弹（放行/拒绝都免），off 恢复原规则；[YOLO] 状态位可见
- [ ] 撤回：按钮点一下退上一轮（消息层，文件/Inbox 不动），悬挂审批作废
- [ ] 三项默认收起在高级菜单；既有 200+ 单测全绿（复用 permissions/commands 纯函数）
