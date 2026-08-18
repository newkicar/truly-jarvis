# ADR-0002: Inbox 唯一写入口与项目内快照回退

**状态:** 已接受（2026-08-18）

## 背景

Vault 是用户的 Obsidian 知识库，JARVIS 需要检索任意笔记，但写入应限制在 Inbox 暂存区。
归档由人在 Obsidian 完成，不由代理执行。Vault 本身是独立 git 仓库；把 Inbox 纳入
vault commit 会污染用户笔记历史，且与 JARVIS 项目内的会话回退两套机制冲突。

## 决策

1. **写边界**：对 `/vault/` 的 `write_file` / `edit_file` / `delete` 仅允许
   `/vault/Inbox/` 内路径；Vault 其它文件夹只读。Inbox 外路径即使 HITL 审批通过也
   由 `VaultWriteGuardMiddleware` 拒绝。定时任务 `save_path` 仅允许 `vault:Inbox/`。
2. **Inbox 不进 vault git**：vault 根 `.gitignore` 排除 `Inbox/`；版本与回退由
   JARVIS 项目负责。
3. **Inbox 快照在项目内**：每次成功写入 Inbox 前，在项目目录
   `inbox_snapshots.sqlite` 记录写前副本，关联 `thread_id` 与 `checkpoint_id`。
4. **会话 `/rollback`**：除现有项目 git 回退外，还原**当前会话**在目标 checkpoint
   之后写过的 Inbox 文件，并列出路径；可覆盖 Obsidian 手改。`sched-*` 线程写入
   不在会话回退范围内。

## 被否决的选项

- **vault git commit Inbox**：污染用户仓库；与项目 `/snapshot` 双轨。
- **JARVIS 自动归档**：必然写入 Inbox 外，违反「只绑定 Inbox」。
- **回退时跳过 Obsidian 手改**：会话无法完整撤回。

## 影响

- 新增 `src/vault_guard.py`、`src/inbox_snapshots.py`、`src/inbox_snapshot_middleware.py`。
- `commands.rollback` 签名扩展为 `(agent, thread_id, checkpoint_id, vault_path)`。
- 术语见仓库根 `CONTEXT.md`。
