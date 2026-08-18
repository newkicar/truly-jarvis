# 06 — 权限对话框完整 diff

**What to build:** HITL 审批 Modal 对 `write_file` / `edit_file`（Inbox 内）展示可读的 diff 预览：新建显示全文摘要，修改显示变更前后对比（或 unified diff 风格），替代当前仅内容摘要的第一版。

**Blocked by:** 05 — TUI 逐 token + Markdown 同屏流式

**Status:** ready-for-agent

- [ ] 审批前读取目标 Inbox 文件写前内容（可与快照或直读 vault 结合）
- [ ] Modal 中间区域展示 diff，长内容截断规则明确（如 ≤30 行 + 「…」）
- [ ] CLI 审批路径可选同步增强（print diff），或文档注明 TUI 优先
- [ ] 单测：`tui_format` / permission preview 对新建与修改两种场景输出预期 markup
