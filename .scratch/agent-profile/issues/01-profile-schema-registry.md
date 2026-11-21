# 01 — Profile Schema / Registry / agent-meta DB / 内置三身份

Status: ready-for-agent
Blocked by: （无）

## What to build

1. `src/profiles/__init__.py`、`schema.py`：
   - dataclass `AgentProfile`（字段按 spec §"ProfileSpec/模块布局"，对应方案 §4.2 全字段：schema_version/id/name/description/identity{role,mission,principles[]}/runtime{engine,model}/instructions{file}/skills{include[],exclude[]}/memory{enabled,namespace,recall{enabled,max_items},write{mode,auto_promote}}/tools{allow[],deny[]}/permissions{filesystem{workspace_only},approvals{execute,external_network,destructive_operations},can_delegate}/session{checkpoint_enabled,checkpoint_policy}/lifecycle{persistent_profile,worker_default}）；
   - `parse_profile(dict) -> AgentProfile` 严格校验：未知**安全**字段（permissions/approvals/filesystem 下的未识别键）→ `ProfileError`（不静默忽略）；未知普通字段 → 宽容但记录（保持前向兼容）；
   - 安全默认 fail-closed：`approvals` 缺省 = required；`filesystem.workspace_only` 缺省 = False（保持现状宽松）但**项目层试图把更严的收紧项放宽为 False 时拒绝**（由 registry 合并规则执行，见 2）；
   - `profile_hash(profile, agents_md_text) -> str`：sha256(yaml 归一化（sorted、去空值）+ AGENTS.md 文本 UTF-8)。
2. `src/profiles/registry.py`：
   - 发现三层：内置（`src/profiles/builtin/`）< 用户（`~/.jarvis/agents/<id>/agent.yaml`，`JARVIS_HOME` 重定向）< 项目（`<workspace>/.jarvis/agents/<id>/agent.yaml`）；不扫描任意磁盘；
   - 合并：低层级为基，高层级逐字段覆盖；**安全段（permissions）高层级只能收窄**——把 allow 改 deny、把 optional 改 required、把 False 改 True 合法；反向（deny→allow、required→optional、True→False）→ `ProfileError`；
   - `ProfileRegistry(user_home=None, workspace=None, jarvis_json_agents=None)`：`list()` / `get(id)`（unknown → `ProfileError`）/ `load(id)`（合并 + 校验 + hash + 读 AGENTS.md）；
   - legacy 映射：`jarvis_json_agents`（现有 `jarvis.json` 的 `agents` 段 dict）中每个名字暴露为**只读虚拟 Profile**（id 与描述映射；无 yaml 正文；`is_legacy=True`；build 时走现有 config_agents 行为，绝不改写原配置）；
   - 加载成功 → upsert `agent_profiles` 行（enabled=1，profile_hash/source_path/created_at/updated_at）。
3. `src/profiles/db.py`：
   - `~/.jarvis/agent-meta.sqlite`（`JARVIS_HOME` 重定向），`schema_migrations(version, applied_at)` + 建 `agent_profiles`（§14 列）；小型 migration runner（幂等、可多版本追加——04/06 会加 memory_entries/memory_candidates/agent_runs，01 先建空表占位也可，推荐 01 建 `agent_profiles` + 空 `agent_runs`/`memory_entries`/`memory_candidates` 表，避免 04/06 再动 schema_migrations 语义——由实现者定，但必须一次把四表 DDL 就位，版本号 1）；
   - 不碰 checkpoint db。
4. 内置三身份 `src/profiles/builtin/{secretary,researcher,developer}/`：`agent.yaml`（§4.2 风格，skill 名必须映射到仓库真实 `skills/` 目录：researcher→web-research；secretary→vault-nav, local-facts；developer→docx, xlsx, pdf；保持最小）+ `AGENTS.md`（短 CJK 身份/使命说明）。
5. `pyproject.toml`：dependencies 加 `pyyaml`（**新增直接依赖**，注明）；`[tool.setuptools.package-data]` 加 `src = ["*.md", "profiles/builtin/**/*.yaml", "profiles/builtin/**/*.md"]`（与现有 `src=["*.md"]` 合并为一条）。
6. 测试（TDD 先写）：`tests/test_agent_profile_schema.py`（§16 Profile 清单：缺省/坏 schema/重复 id/引用不存在的 skill-tool 宽松记录/版本与 hash 变化/项目覆盖冲突与安全段扩权拒绝）+ `tests/test_profile_registry.py`（三层发现、合并、legacy 映射、db upsert、JARVIS_HOME 重定向）。

## Acceptance

- [ ] 新测试全绿（目标套件）；
- [ ] 全量 pytest vs 基线无新增失败；
- [ ] `python -c "import src.profiles"` 可用；
- [ ] commit（含 spec + issues + 本票全部改动 + pyproject），message UTF-8 文件，注明 pyyaml 为新增依赖。
