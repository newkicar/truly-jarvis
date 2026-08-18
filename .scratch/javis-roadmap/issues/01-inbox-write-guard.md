# 01 — Vault 写边界：仅 Inbox 可写

**What to build:** 任意代理（主代理、子代理、定时任务触发的写入）对 Vault 的创建/修改/删除，一律限制在 Inbox 内。Inbox 外路径即使 HITL 审批通过也直接拒绝并返回明确错误。定时任务的 `save_path` 若不在 Inbox 则启动或执行时报错。用户仍可只读检索 Vault 任意笔记。

**Blocked by:** None — can start immediately

**Status:** done

- [ ] 主代理对 `/vault/` 的 `write_file` / `edit_file` / `delete`：路径不在 Inbox 时 middleware 拦截，不执行工具
- [ ] `knowledge_keeper` 现有 Inbox 守卫与主代理守卫共用同一套路径判定逻辑
- [ ] 定时任务解析 `save_path` 时拒绝非 `vault:Inbox/`（或等价 Inbox 前缀）的配置
- [ ] 单测：Inbox 内写入放行、Inbox 外写入拒绝、scheduler 非法 save_path 拒绝
