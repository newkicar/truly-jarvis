# 04 — Memory Router 六命名空间（recall/propose/curate + legacy 分类迁移）

Status: ready-for-agent
Blocked by: 01

## What to build

1. `src/memory_router.py`：
   - 六命名空间（§8.2）：User `~/.jarvis/memory/user/{profile,preferences}.md`；Secretary `~/.jarvis/memory/secretary/{MEMORY,operating-lessons}.md`；Agent `~/.jarvis/agents/<id>/memory/`；Project `~/.jarvis/projects/<p>/memory/{background,decisions,progress}.md`；Task `~/.jarvis/tasks/<tid>/{working-memory.md,memory-candidates/}`；Checkpoint = checkpointer 负责，不入 router（文档说明）；
   - `for_worker(profile_id, task_id, project_id, access_policy) -> MemoryRouter`：
     - `.recall(query, scopes=, token_budget)`：索引优先（MEMORY.md）；无索引 ns 回落文件标题+首行；char/4 预算；记录来源；
     - `.propose(namespace, content, source_task_id=)`：append-only JSON 候选：candidate_id=uuid、source_task_id、source_agent_id、target_namespace、memory_type、content、source_reference、confidence（nullable，禁止臆造）、created_at ISO-8601、status=pending_review；同一 SQLite 事务 upsert `memory_candidates`；
     - `.curate(candidate_id, decision, reviewer)`：approve→追加目标 ns 文件 + 插 `memory_entries`（单 SQLite 连接 `BEGIN IMMEDIATE`）；reject→更新 status；
   - Worker 默认权限代码强制：read=own task/own agent/shared project/user（只读）；write=own task working-memory only；propose=agent/project/user candidates only；
   - legacy：`classify_legacy_memory(mem_dir)->report`（user-*→user-preference，secretary*→secretary-lesson，project-*→project-knowledge，else→legacy）；`migrate_legacy_memory(report, target)` 显式-only（备份→分类写→迁移日志→保留原件），从不自动执行。
2. 测试：`tests/test_memory_router.py`（权限边界拒绝、并发写、JARVIS_HOME 重定向、自建目录纪律、legacy 分类与迁移幂等）。

## Acceptance

- [x] 目标套件全绿；
- [x] 全量 vs 基线无新增失败；
- [x] commit（UTF-8 message 文件）。
