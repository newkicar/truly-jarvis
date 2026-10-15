# ADR-0007: manual-only skill（frontmatter disable-model-invocation）

**状态:** 已接受（2026-10-15）

## 背景

Agent Skills 约定里 `disable-model-invocation: true` 的 SKILL.md 只允许用户手动调用，模型不应自动发现。deepagents 的 SkillsMiddleware 用 yaml.safe_load 解析 frontmatter 但**丢弃**该键（只取 name/description/allowed-tools/compatibility/metadata/license），注入点唯一（modify_request 把 skills 清单追加进 system message），且 create_deep_agent(skills=...) 内部自装配原生类、无法替换实现。

## 决策

1. **子类化**：`src/jarvis_skills.py` 的 `JarvisSkillsMiddleware(SkillsMiddleware)`——before_agent 继承原生加载；modify_request 覆写：按 `skill_discovery.discover_skill_catalog`（自家 frontmatter 解析，含 `manual_only` 标志）把 flagged skill 从提示词清单中剔除，其余条目与原生格式一致。flag 以**读盘**为准（catalog 层优先级覆盖语义与原生 last-one-wins 对齐），不经后端。
2. **装配切换**：agent.py 不再传 `skills=`（graph.py 原生 SkillsMiddleware 与 general-purpose 子代理的 skills 注入随之消失），改把子类挂进 `middleware=`。researcher / knowledge_keeper 等自定义子代理本来就不带 skills 层，语义不变；GP 子代理失去 skills 提示词（其为通用文件/shell 子代理，skill 发现职责归主代理——可接受的行为变更，文档注明）。
3. **手动调用载体 = `/use <skill> [说明]`**：读盘上 SKILL.md 全文（剥 frontmatter）作为本轮 user 消息注入（`[skill:<name>]` 标记 + 可选任务说明）；TUI 与 CLI 同入口（commands.build_skill_use_message）。模型可见（未 flag）的 skill 同样可 `/use`（统一入口）；`/skills` 列出全目录，manual-only 打 `[manual]` 标记；`/doctor` skills 表加 manual-only 列。
4. **上下文隔离**：flagged skill 的 frontmatter 介绍（name/description）在未被 /use 调用的任何轮次都不进模型 system prompt；/use 注入的是正文全文（用户主动行为，允许全量）。

## 被否决的选项

- **传 skills= + 后置过滤 middleware**：原生 modify_request 已把全量清单追加进 system message，后置只能再追加一份过滤清单，原始泄漏仍在。
- **源目录拆分（manual 单开一层目录）**：强迫用户挪文件，破坏「与 Claude/opencode 同目录可混用」的目标。
- **把 flag 塞进 SkillMetadata.metadata 让原生类认**：原生 _format_skills_list 不读 metadata，白改。

## 影响

- 新增：`src/jarvis_skills.py`；变更：agent.py 装配、skill_discovery（SkillMeta +manual_only +fs_path）、commands（/use、/skills）、SLASH_COMMANDS、TUI _handle_user_message /use 拦截、main.py CLI /use 分支、/doctor 表。
- 测试：flag 剔除 / 未 flag 保留 / 模板 None / agent 装配类 / build_skill_use_message 各分支 / catalog 标记。