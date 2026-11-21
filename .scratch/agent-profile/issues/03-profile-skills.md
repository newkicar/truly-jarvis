# 03 — Profile Skill 分层解析（common < agent < project < task）

Status: ready-for-agent
Blocked by: 01, 02

## What to build

1. `src/profile_skills.py`：
   - 分层低→高：common（`~/.jarvis/skills/common/`，复用现有 user skills root 子目录，不新增 vpath，resolver 仅声明其为层）< agent（`~/.jarvis/agents/<id>/skills/` 路由 `/agent-skills/`）< project（`~/.jarvis/projects/<p>/skills/` 路由 `/project-skills/`）< task（可选 task 级目录，经 task_context 传入）；
   - `resolve(profile_id, workspace, task_context=None, ...) -> ResolvedSkillManifest{entries[{name,tier,fs_path,content_hash}], conflicts, excluded, manifest_hash}`；
   - 同名冲突 = 高层级胜出 + 记录 conflict 条目；`profile.skills.include/exclude` 过滤生效；legacy `config.skills` 路径照常加载；
   - 接入 02 的 `bake_spec`：有 profile 时 spec.skill_vpaths/skill_routes/skill_manifest_hash 给出真值（02 中先留 None 占位）。
2. 测试：`tests/test_profile_skills.py`（层级优先级、冲突记录、include/exclude、manifest_hash 稳定性、与 bake_spec 接线、JARVIS_HOME 重定向、自建目录纪律）。

## Acceptance

- [x] 目标套件全绿；
- [x] 相关套件（skills/skill_discovery/config/agent）vs 基线无新增失败；
- [x] commit（UTF-8 message 文件）。
