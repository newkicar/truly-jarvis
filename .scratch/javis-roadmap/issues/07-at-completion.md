# 07 — @ 文件路径补全

**What to build:** TUI 输入框输入 `@` 时弹出补全列表，优先 `/vault/` 与 `/vault/Inbox/` 下的笔记路径，可选包含 `/workspace/`。选中后插入输入框，减少写错路径导致守卫拒绝。

**Blocked by:** 06 — 权限对话框完整 diff

**Status:** ready-for-agent

- [ ] `@` 触发补全 Overlay 或 Textual 等价组件
- [ ] 列表来源：vault 下 `.md` 实时扫描（Inbox 优先排序），workspace 可选
- [ ] 键盘选择 + Enter 插入；Esc 关闭
- [ ] 单测或 run_test：输入 `@` 后出现候选、选中后 Input 值含路径
