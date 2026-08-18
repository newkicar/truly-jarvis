# 02 — Inbox 快照：写入前自动记录

**What to build:** 每次成功向 Inbox 写入（新建、修改、删除）前，在 JARVIS 项目内保存该文件的写前状态，并关联当前 `thread_id` 与会话检查点 id。新建文件记「写前不存在」。快照不进入 Vault git，也不依赖手动 `/snapshot`。

**Blocked by:** 01 — Vault 写边界：仅 Inbox 可写

**Status:** done

- [ ] 写前快照在 Inbox 守卫通过后、工具实际执行前触发（或执行成功后与检查点对齐，需保证可还原写前状态）
- [ ] 快照持久化在项目目录（如 SQLite 或按文件副本），记录：相对 Inbox 路径、写前内容或「不存在」标记、`thread_id`、`checkpoint_id`、时间戳
- [ ] 定时任务线程（`sched-*`）的写入同样打快照，但 `thread_id` 可区分来源
- [ ] 单测：写入 Inbox 后快照可查；写前无文件时标记正确
