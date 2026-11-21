# 06 — JarvisRuntime 多身份运行时（Worker 隔离 + agent_runs 审计）

Status: ready-for-agent
Blocked by: 02, 04

## What to build

1. `src/jarvis_runtime.py`：
   - `create(profile_id, workspace, *, task_id, session_id=None, project_id=None, checkpointer=None, store=None, profile_version=None) -> RuntimeHandle`；
   - 校验：workspace 必须 is_dir；pinned `profile_version` 必须在 registry 存在否则 raise；
   - handle：`.invoke(message)` 返回 §12.2 dict（runtime_id/profile_id/profile_version/task_id/session_id/status/result/artifacts[]/memory_candidates[]/usage）；`.stream(message)`（stream_events v3 + RunControl，ADR-0008 风格）；`.resume()` 仅在给了 checkpointer 时可用；`.close()`；`.metadata`=ProfileSnapshot+runtime_id；
   - thread_id = session_id 或 task 级；`agent_runs` 行：create 时 insert，invoke/complete/fail/cancel 时 update status+finished_at；
   - 跨 profile 不共享 checkpointer；legacy `create_jarvis(profile_id=None)` 行为不变。
2. 测试：`tests/test_jarvis_runtime.py`（fake model + InMemory checkpointer；双 Worker 隔离；agent_runs 审计；pinned version 校验拒绝；resume/close 生命周期）。

## Acceptance

- [ ] 目标套件全绿；
- [ ] 全量 vs 基线无新增失败；
- [ ] commit（UTF-8 message 文件）。
