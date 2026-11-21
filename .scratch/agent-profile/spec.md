# Agent Profile 多身份运行时 — 实现 Spec

- Status: ready-for-agent
- 权威设计源：`.scratch/_plan_utf8.md`（仓库根实施方案的 UTF-8 干净副本，§1–§22）
- 代码基线：main @ `df7e436`
- 工单：`.scratch/agent-profile/issues/01..07`（顺序实施 01→07，每票一个 commit）

## Problem（问题）

当前 Jarvis 只有单一固定身份：所有会话共享同一套 system prompt、同一份全局记忆（`~/.jarvis/memory/*.md`）、同一套 skill 发现路径（用户层 + 项目层）、同一套工具与权限。无法：

1. 为"秘书 / 研究员 / 开发者"等持久逻辑身份（Agent Profile）分别定制身份指令、技能、记忆、工具与权限；
2. 在同一内核上并发运行多个 Worker，且彼此任务记忆、Checkpoint、工作目录完全隔离；
3. 让上层（Local Dots 等）通过 `create(profile_id, workspace, task_id, ...)` 获得带运行时记录的句柄；
4. 安全地把文件操作关进 workspace、把高危操作（execute / 外网 / 破坏性操作）落到"必须审批"，且项目级只能收窄、不能放宽；
5. 为 Profile 本体（YAML）建立版本化元数据（agent-meta sqlite），并留下可观测事件流。

同时**不得破坏**现有 TUI / CLI / GUI / Headless 默认行为：`profile_id=None` 的路径必须与现状字节级等价（全部旧测试不新增失败）。

## Solution（方案）

在现有实现上增量新增 5 个能力，全部复用现有内核（deepagents 0.7.6 + langchain 1.3.x）；不复刻内核、不 fork、不引入常驻进程 / 向量库 / 消息队列：

1. **Profile 层（ticket 01）**：`src/profiles/` 包 — YAML schema（dataclass + 严格校验，未知安全字段 fail-closed）、三层发现（内置 < 用户 `~/.jarvis/agents/<id>/` < 项目 `<workspace>/.jarvis/agents/<id>/`）、合并规则（安全段只可收窄）、legacy `jarvis.json agents` 读映射、agent-meta sqlite（`schema_migrations` + `agent_profiles`）、3 个内置 Profile（secretary / researcher / developer，AGENTS.md 为 CJK 身份说明，随包分发）。
2. **Runtime Builder（ticket 02）**：纯函数 `bake_spec(config, profile, workspace, task_id, project_id) -> ProfileSpec`（冻结、可缓存）；`build_agent(..., profile_spec=None)` 接缝（None = 原流程）；Profile 级模型覆盖 + harness 按模型注册；工具 allow/deny 过滤；权限规则合并（只收窄）；memory 目录扩展；skill 路由扩展；`ProfileSnapshot` 挂 compiled agent；`create_jarvis(profile_id=None, ...)` 新参数（None 完全兼容）。
3. **Profile-aware Skills（ticket 03）**：`src/profile_skills.py` 分层解析器（common / agent / project / task 层，同名高层级胜出 + 冲突记录），`ResolvedSkillManifest`（含 manifest_hash）；legacy `config.skills` 路径继续加载。
4. **Memory Router（ticket 04）**：`src/memory_router.py` 六类记忆（User / Secretary / Agent / Project / Task / Checkpoint）目录布局，按 Worker 权利模型的 `recall`（索引优先、预算裁剪）与 `propose`（候选 JSON + `memory_candidates` upsert；confidence 可 null、绝不编造）、`curate`（approve 追加 + `memory_entries` 写入，单 SQLite 连接 `BEGIN IMMEDIATE` 串行化）；legacy 记忆**分类报告 + 显式迁移**（绝不自动）。DDL：`memory_entries` / `memory_candidates`。
5. **文件/权限安全（ticket 05）**：`src/file_guard.py` 真实路径包含性检查（`Path.resolve()`，防 `..` 与符号链接逃逸、Windows 盘符边界，不做字符串前缀判断）；`WorkspaceFileGuardMiddleware` 按 deepagents 工具**实测**参数名拦截；`permissions.approvals`（execute / external_network / destructive_operations = required）转追加权限规则（deny-wins 交集）；审计 JSONL（`~/.jarvis/audit/permissions.jsonl`，脱敏）。
6. **Runtime 句柄（ticket 06）**：`src/jarvis_runtime.py` `create(profile_id, workspace, *, task_id, ...)` → handle（invoke/stream/resume/close + metadata）；thread_id = session_id 或 task 级；`agent_runs` 记录生命周期；legacy `create_jarvis(profile_id=None)` 不变。
7. **可观测 + 诊断（ticket 07）**：`src/profiles/observability.py` 事件 JSONL（`~/.jarvis/ops/events.jsonl`，§19 事件族，脱敏）；diagnostics（list/validate/memory view/skill report/permission diagnose）；CLI `--profiles [id] [--validate]` + TUI `/profiles`（commands.py 共用）+ GUI 安全 no-op。

## User Stories（用户故事）

- 作为用户，我可以创建 `~/.jarvis/agents/secretary/agent.yaml`，让 Jarvis 以"秘书"身份运行：独立身份 prompt、技能白名单、记忆空间、权限策略。
- 作为用户，我在项目里放 `.jarvis/agents/<id>/agent.yaml` 可覆盖同 id 的普通配置，但**不能**放宽安全段（放宽被拒绝 / 生效为收窄）。
- 作为上层程序（Local Dots），我调 `create("developer", workspace, task_id=...)` 得到 handle；并发 invoke 不互相污染；`agent_runs` 留痕。
- 作为用户，developer Worker A 提交记忆候选后，我 review 并 approve，晋升到 developer 命名空间；Worker B 立即可读；researcher 默认读不到 developer 的记忆。
- 作为用户，secretary Profile 的 `workspace_only: true` 生效后，write/edit/delete 越出 workspace 直接被拒（含 `..` 与符号链接）。
- 作为用户，默认路径（不指定 profile）体验与升级前完全一致。

## Implementation Decisions（实现决策）

### 模块布局（均在现有 `src/` 平铺布局下）

- `src/profiles/`：`__init__.py`、`schema.py`、`registry.py`、`db.py`、`builtin/{secretary,researcher,developer}/{agent.yaml,AGENTS.md}`（随包分发；AGENTS.md 短 CJK 身份说明）。
- `src/profile_skills.py`（03）、`src/memory_router.py`（04）、`src/file_guard.py`（05）、`src/jarvis_runtime.py`（06）、`src/profiles/observability.py` + `src/profiles/diagnostics.py`（07）。

### ProfileSpec（02 的核心，"baked" 冻结对象，每次调用由纯函数生成）

```
bake_spec(config, profile|None, workspace, task_id, project_id) -> ProfileSpec
ProfileSpec(
  profile_id / profile_version / profile_hash / source,   # hash = sha256(归一化合并后 yaml + AGENTS.md 文本)
  model_id,            # None = 用 config.model_id
  prompt_suffix,       # 身份 identity 块 + AGENTS.md 文本（bake 时固化）
  memory_dirs,         # tuple，额外记忆目录（其 *.md 追加进 memory=）
  skill_vpaths, skill_routes, skill_manifest_hash,  # 03 提供；None 回落 legacy
  tools_allow, tools_deny,       # tuple；deny 并入权限规则为 "deny"
  permission_extra_rules,        # dict（仅收窄）；merged = {**config.permissions, **extra}
  workspace_only_filesystem, tool_policy_hash,
)
```

- **agent.py 接缝**：`build_agent(..., profile_spec: ProfileSpec | None = None)`；None 走**原样**旧路径（门控测试：工具/提示词组成/harness 注册键与现状一致）。有 spec 时：
  - 模型：`_make_model(config, model_id=spec.model_id)` + 按该 model 注册 harness profile（幂等）；
  - system_prompt = `build_main_prompt(config)` + 冲突措辞段（平台安全 > 全局 > 身份 > 项目）+ 身份块 + AGENTS.md 文本；
  - memory files = 现状 `config.memory_dir/*.md` + `spec.memory_dirs` 各目录 `*.md`（均除 README）；
  - backend：`_make_backend(config, extra_skill_routes=...)`（03 的 vpath→fs 路由并入 CompositeBackend）；
  - main_tools = (quick_search + mcp_tools) 先按 `tools_deny` 剔除、再按 `tools_allow` 取子集（allow 为空 = 不过滤）；
  - 权限：`merged_rules = {**config.permissions, **spec.permission_extra_rules}`，`tools_deny` 中每个工具追加规则 `{"<tool>": "deny"}`（字符串规则；fnmatch 最后匹配胜出语义不变），交给现有 `build_permission_interrupts(merged_rules, ...)` 路径（**不改 permissions.py 既有函数签名**，合并逻辑做在 02/05）；
  - snapshot：`ProfileSnapshot{profile_id, profile_version, profile_hash, runtime_version, engine="deepagents", task_id, session_id, workspace}` 挂到 compiled agent（属性 `_jarvis_profile_snapshot`；legacy = None）。
- **缓存（§10.4）**：只缓存 baked 输入（key ≥ (profile_hash, model, skill_manifest_hash, tool_policy_hash)），**不缓存 compiled agent**（checkpointer/state 生命周期问题）；暴露 hit/miss 计数给 07。
- `create_jarvis(workspace, *, profile_id=None, task_id=None, project_id=None, ...)`：`profile_id=None` → 原流程；否则 registry 解析 + bake + build_agent。

### 目录布局（§8.2，全部在 `~/.jarvis`；`JARVIS_HOME` 可重定向 → 测试全部走 env 重定向）

```
~/.jarvis/
  agents/<id>/agent.yaml、AGENTS.md、skills/、memory/
  projects/<p>/skills/、memory/{background,decisions,progress}.md
  tasks/<tid>/working-memory.md、memory-candidates/
  memory/user/{profile,preferences}.md
  memory/secretary/{MEMORY,operating-lessons}.md
  ops/events.jsonl、audit/permissions.jsonl
  agent-meta.sqlite          # schema_migrations + agent_profiles + agent_runs
                              # + memory_entries + memory_candidates
```

- `agent-meta.sqlite` 是**独立**小库（自己的 migration runner：`schema_migrations` 表 + 版本号），**不碰** checkpoint db（`<project_root>/checkpoints/checkpoints.sqlite`）。
- Checkpoint 属 §8.1 第六类记忆（会话回退），**不进** memory router，文档写明。
- 记忆本体仍是**文件**（可看可改）；SQLite 只存索引 / 版本 / 候选元数据。

### Skill 分层（§7.3，ticket 03）

- 层（低→高）：common（`~/.jarvis/skills/common/`，沿用现有用户 skills 根下子目录，不新增 vpath，resolver 只把它声明为一层）< agent（`~/.jarvis/agents/<id>/skills/` → vpath `/agent-skills/`）< project（`~/.jarvis/projects/<p>/skills/` → vpath `/project-skills/`）< task（可选参数）。
- `resolve(profile_id, workspace, task_context) -> ResolvedSkillManifest{entries[{name, tier, fs_path, content_hash}], conflicts, excluded, manifest_hash}`；同名 = 高层级胜出 + 冲突记录；profile.skills.include/exclude 生效；legacy `config.skills` 路径继续加载（§13.3 兼容）。

### Memory 权利模型（§8，代码强制，非提示词）

Worker（profile 实例）默认权：
- 读：own task / own agent / 共享 project / user（只读）；
- 写：own task working-memory（append-only 文件）；
- 提案：可向 agent / project / user 命名空间写 candidate（JSON 字段：candidate_id=uuid、source_task_id、source_agent_id、target_namespace、memory_type、content、source_reference、confidence（**可 null，绝不编造**）、created_at ISO-8601、status=pending_review；同时 SQLite upsert，单事务）；
- 晋升：`curate(candidate_id, decision, reviewer)`：approve → 追加目标命名空间文件 + `memory_entries` insert（`BEGIN IMMEDIATE` 串行）；reject → 更新 status。
- legacy：`classify_legacy_memory(mem_dir) -> report`（启发式：`user-*`→user-preference、`secretary*`→secretary-lesson、`project-*`→project-knowledge、其余→`legacy`）；`migrate_legacy_memory(report, target)` **仅显式调用**：先备份 → 分类写入 → 迁移日志 → 保留原件。绝不自动触发。

### 文件边界（§9.4，ticket 05）

- `resolve_within(base, requested) -> Path`：`Path.resolve()` 实路径包含性（防 `..` 与符号链接）；Windows 盘符不同 = 拒绝；UNC 处理；**不做**字符串前缀判断；越界抛 `PathBoundaryError`。
- `WorkspaceFileGuardMiddleware`（wrap_tool_call）：对 write_file/edit_file/delete（以及 workspace_only 时的读类工具）按**实测的 deepagents 工具参数名**解析目标路径（实现前必须先内省 deepagents 0.7.6 工具 schema，禁止猜参数名）。
- 有效策略 = Registered ∩ Global ∩ Caller ∩ Profile-allow ∩ Project-policy，**deny-wins**；模糊即 fail-closed（回落最严格，不回落宽松）。
- 审计：每次权限决策追加 JSONL 到 `~/.jarvis/audit/permissions.jsonl`（脱敏：不写完整参数原文，写前缀/哈希/摘要）。

### 安全原则（§4.3 / §22，硬约束）

- 未知安全字段**不静默忽略** → 校验器报错（`ProfileError`）；
- 配置错误**不得**回落宽松默认；
- 项目/调用方层只能**收窄**安全段（加 deny/ask），放宽即拒绝；
- Prompt 里写权限 ≠ 安全控制，一切以代码强制为准；
- 运行中 Worker 持有创建时 Profile 快照，**不做**在途变更；
- 跨 Profile 不共用 checkpointer；
- 日志/事件/审计**不含**敏感记忆内容、凭据、完整 prompt、用户 PII（测试断言）。

### 兼容（§13）

- legacy `jarvis.json agents` 的名字以**只读虚拟 Profile** 暴露（registry 读映射，行为不变，绝不改写原配置）；
- 旧 `create_jarvis()`、旧配置、旧 SubAgent（researcher/knowledge_keeper 默认不变）、旧 skill 路径、旧 memory、TUI/CLI/Headless 全保留。

## Testing Decisions（测试决策）

- 全部新测试**先写**（TDD），用 `os.makedirs` 自建目录纪律（**禁用** pytest `tmp_path` / `tempfile.mkdtemp`——本机 WinError 5 中毒）；
- 所有 `~/.jarvis` 相关测试用 `JARVIS_HOME` env 重定向到自建目录；项目根用 `JARVIS_PROJECT_ROOT`；
- GUI 测试 `QT_QPA_PLATFORM=offscreen`；
- 每 ticket：目标套件 → 相关套件（agent/config/permissions/skills/commands/tui）→ 全量 `python -m pytest tests -q` 与基线 `.scratch/_baseline_full.txt` 对比（基线 EXIT=3、约 4 个预存失败 + APScheduler/GC 原生崩溃导致 ~26% 处中止；**不允许新增失败**）；
- 关键门控测试（02）：`profile_spec=None` 时 build_agent 的工具集 / system prompt 组成 / harness 注册键与旧行为一致（旧全量测试不新增失败即回归门）；
- 安全测试（§16）：`../` 穿越、盘符跨界、UNC、符号链接跨界、未注册工具调用、deny 调用、项目尝试扩权、并发记忆写入；
- 端到端（§16 最小 10 步）：researcher + developer 双 Worker 同内核、不同身份/技能/记忆/工作区、候选晋升、清理任务目录、重建无串用；
- §16 各清单（Profile / Runtime / Memory / Skills / 安全 / 兼容）逐条映射到上表测试文件。

## Out of Scope（范围外）

- §15 Phase 7 动态委派（profile-backed subagent、fan-out）——留后续；
- 向量数据库 / 消息队列 / 常驻 Worker 进程 / 微服务；
- 依赖升级（deepagents/langchain 锁版本不动；本任务**新增** `pyyaml` 一个直接依赖，随 01 提交并在 commit message 注明）；
- legacy 记忆/配置的**自动**迁移（只提供报告 + 显式迁移器）；
- GUI 端 Profile 管理界面（07 只做安全 no-op，不新增 GUI 面板）。

## Further Notes（备注）

- 提交纪律：每 ticket 一个 commit（main）；commit message 写 UTF-8 文件再 `git commit -F`（控制台 CP=936 不能直接输中文）；spec + issues 随 01 的 commit 一起入库；
- `.scratch/` 辅助文件（`_plan_utf8.md`、`_baseline_full.txt`、`_read.py` 等）保持 untracked；仓库根那份乱码方案文档**绝不**提交；
- 内置 3 个 Profile 的 skill 名必须映射到仓库 `skills/` 真实目录（§18：如 researcher→web-research、secretary→vault-nav/local-facts、developer→docx/xlsx/pdf，保持最小且真实存在）；
- 交付报告中文（每 ticket 一段 + 回滚边界 + 最终汇总）。
