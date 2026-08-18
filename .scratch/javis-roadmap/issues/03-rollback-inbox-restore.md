# 03 — 会话 /rollback 还原 Inbox

**What to build:** 用户执行 `/rollback <checkpoint>` 时，除现有项目 git 回退外，按检查点还原**该会话 thread** 在 Inbox 中写过的文件：写前无文件则删除该 Inbox 笔记；有则恢复写前内容（覆盖 Obsidian 手改）。命令输出必须列出将还原或删除的 Inbox 路径。定时任务（`sched-*`）写入的 Inbox 文件不在会话回退范围内。

**Blocked by:** 02 — Inbox 快照：写入前自动记录

**Status:** done

- [ ] `/rollback` 根据目标 checkpoint 与当前 thread_id 查询 Inbox 快照并执行文件还原
- [ ] 输出文本包含 Inbox 影响清单（路径 + 操作：还原/删除）
- [ ] 不还原其它 thread（含 sched-*）的 Inbox 写入
- [ ] CLI 与 TUI 共用 `commands.py` 逻辑，行为一致
- [ ] 单测：模拟会话写入 → rollback → Inbox 文件状态与写前一致；sched 写入不被误删
