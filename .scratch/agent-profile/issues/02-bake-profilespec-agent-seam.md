# 02 — ProfileSpec 烘焙 + agent.py 接缝（Runtime Builder 内核）

Status: ready-for-agent
Blocked by: 01

## What to build

1. `src/profiles/spec.py`（或 `src/profile_spec.py`，实现者定，保持与 01 包风格一致）：
   - frozen dataclass `ProfileSpec`（字段见 spec §ProfileSpec）+ `ProfileSnapshot`（§12 响应 metadata 用）；
   - 纯函数 `bake_spec(config, profile, workspace, task_id, project_id, session_id=None) -> ProfileSpec`：profile 为 None 时返回 None（不造对象）；AGENTS.md 缺失 = prompt_suffix 只含 identity 块（不报错）；
   - 缓存：`_BAKE_CACHE`（key ≥ (profile_hash, model, skill_manifest_hash, tool_policy_hash)）+ `bake_cache_stats()`（hit/miss 计数，供 07 观测）。
2. `src/agent.py` 接缝（改动最小化）：
   - `build_agent(config, model=None, checkpointer=None, store=None, permission_state=None, mcp_tools=None, jump_in_registry=None, profile_spec=None)`；
   - `profile_spec=None` → **原流程字节级不变**（不动默认路径的任何行）；
   - 有 spec 时：模型 `_make_model(config, model_id=spec.model_id)`（新增可选参数；None=config.model_id）+ 按该 model id 注册 harness（复用现有幂等 `_HARNESS_REGISTERED` 机制）；system_prompt 追加 spec.prompt_suffix + 冲突措辞段；memory files 追加 `spec.memory_dirs`；backend 追加 `spec.skill_routes`（`_make_backend(config, extra_skill_routes=None)`）；main_tools 按 allow/deny 过滤；权限规则合并（`{**config.permissions, **spec.permission_extra_rules}` + deny 工具规则，作为 merged 传入现有 `build_permission_interrupts`/state 构建路径）；
   - compiled agent 挂 `_jarvis_profile_snapshot`（None = legacy）；
   - `create_jarvis(workspace, checkpointer=None, *, model=None, store=None, env_overrides=None, permission_state=None, mcp_tools=None, profile_id=None, task_id=None, project_id=None, session_id=None)`：`profile_id=None` 走原路径（不 import 不触碰 registry 也可——保持零行为差异）；否则 `ProfileRegistry().load(profile_id)` → `bake_spec(...)` → `build_agent(..., profile_spec=)`。
3. 测试：`tests/test_agent_profile_runtime.py`（bake 纯函数/缓存/None 门控：用 fake 记录断言默认路径与改动前一致（工具列表、prompt 段数、harness 键）；有 spec 时 prompt 含身份块、memory 目录文件追加、工具过滤、权限 deny 生效（复用 permissions 测试风格，不真调模型——build_agent 可用 checkpointer=InMemory、model 用现有测试 fake/monkeypatch 模式））。

## Acceptance

- [ ] 默认路径门控测试绿（旧套件 agent/config/permissions/streaming/commands 无新增失败）；
- [ ] spec 各字段行为测试绿；
- [ ] 全量 vs 基线无新增失败；
- [ ] commit（UTF-8 message 文件）。
