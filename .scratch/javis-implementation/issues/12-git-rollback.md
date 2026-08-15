# 12 — git 文件回退（/rollback）

**What to build:** 一期已实现**会话回退**（checkpointer 原生 /replay /fork）。二期补**文件状态回退**：项目目录有文件变更时，每轮对话结束自动 git 提交并记录 {thread_id, checkpoint_id, commit_hash} 映射；`/rollback <checkpoint_id>` 按 checkpoint 把项目文件重置到对应提交，与会话回退对齐。vault 不纳入（独立 git 仓库，依赖 Obsidian 恢复兜底，设计文档 §10.4）。

**Blocked by:** —（二期独立）

**Status:** resolved

## 实现（src/time_travel.py）

- `snapshot(root, thread_id, checkpoint_id)`：项目目录有未提交变更时 → `git add -A`（gitignore 已排除 sqlite/.env/密钥）→ commit `javis <checkpoint_id>` → 映射写入 `git_mapping.sqlite`；无变更返回 None。
- `get_commit(root, checkpoint_id)` / `list_snapshots(root)` / `rollback(root, checkpoint_id)`。
- `_stream_turn` 每轮结束用 `agent.get_state()` 取 checkpoint_id → 调 `snapshot()`；`except Exception: pass` 兜底，不阻塞对话。
- CLI：`/snapshots` 列快照、`/rollback <id>` 回退。

## 关键决策

- **手动快照**：不用「每轮自动 commit」（会刷爆 git 历史，用户不接受）。改为用户主动 `/snapshot` 时，把当前项目文件状态 git 提交并记录到当前 checkpoint。
- **语义**：checkpoint 映射到「手动打快照时的文件状态」——回退到 c1 = 恢复打快照时的文件。
- **映射库 sqlite**：`git_mapping.sqlite` 被 `*.sqlite` gitignore 覆盖，不随快照提交。

## 验收

- [x] `snapshot` 有变更才提交并记录映射、无变更返回 None
- [x] `rollback` 按 checkpoint 恢复文件到对应提交；未知 id 返回 None
- [x] `list_snapshots` 正确列出
- [x] CLI `/snapshot` `/snapshots` `/rollback` 命令可用（手动，无自动 commit）
- [x] 单测：tests/test_time_travel.py（3 个）