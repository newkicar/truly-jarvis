# 04 — 权限审批 Modal（放行/永久放行/拒绝/编辑参数）

**What to build:** TUI 里的 HITL 审批：当 `stream_events` 消费过程中遇到 HITL 中断（`stream.interrupts` 非空）时，挂起 worker、弹出权限审批覆盖层，展示工具名/路径/命令预览，用户用按钮选择后继续对话。对标 opencode 的 permission 对话框，但为 JARVIS 扩展出「编辑参数」。

**Blocked by:** 03 — 流式输出 + 消息样式

**Status:** done

- [ ] worker 检测 `stream.interrupts` → 暂停流式消费 → `push_screen(PermissionModal)`
- [ ] `PermissionModal(ModalScreen)`：顶部 `Tool: <名>` + `Path: <路径>`（execute 显示 Command、write/edit 显示 File）；中间内容预览 viewport；底部 4 按钮：`放行 (a)` / `永久放行 (s)` / `拒绝 (d)` / `编辑参数 (e)`
- [ ] 按钮支持左右键/Tab 切换高亮、Enter 确认、快捷键直达（对标 opencode 键位）
- [ ] 「放行」→ 返回 `{"decisions": [{"type": "approve"}]}`，worker 用 `Command(resume=...)` 继续
- [ ] 「永久放行」→ `apply_permission_override` + `dump_permissions_json` 写回 javis.json + 更新共享 `permission_state`，再放行
- [ ] 「拒绝」→ 返回 `{"type": "reject", "message": ...}`，模型收到拒绝原因
- [ ] 「编辑参数」→ 弹出 `EditParamsModal`：逐 key Input 预填原值，确认后返回 `{"type": "edit", "edited_action": {...}}`
- [ ] 审批返回结构与 CLI `_handle_interrupts` 的契约一致（复用现有 resume 机制），CLI 审批逻辑零改动
- [ ] 用 `run_test` 冒烟：构造含中断的 fake stream → Modal 弹出 → 模拟按键选择 → worker resume 不崩溃