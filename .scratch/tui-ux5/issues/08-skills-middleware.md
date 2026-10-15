# 08 — JarvisSkillsMiddleware（disable-model-invocation 支持）

**What to build:** 新 `src/jarvis_skills.py`：`JarvisSkillsMiddleware(SkillsMiddleware)`，`__init__(backend, sources, flagged: set[str])`；modify_request：flagged 为空 → super()；否则复刻 base 模板填充但 skills_metadata 先按名过滤（`[s for s in ... if s["name"] not in self.flagged]`，_format_skills_list/_format_skills_locations/append_to_system_message 复用）；awrap_model_call 默认委托 modify_request（已核实 base 无独立 async 模板路径）。agent.py 装配：停传 `skills=skill_virtual_sources(config)`，backend 取一次实例共享给子类，middleware 列表追加 `JarvisSkillsMiddleware(backend, sources, flagged=catalog 中 manual_only 名)`。副作用：GP 子代理失去 skills 注入（ADR-0007 已注明可接受）；researcher/knowledge_keeper 原本无 skills middleware，语义不变。

**Type:** task
**Status:** done
**Blocked by:** 09（catalog manual_only 字段）

## 验收
- [ ] 单测：flagged 名不出现在注入的 system；非 flagged 名保留；flagged 为空时与原生 SkillsMiddleware 输出一致
- [ ] agent.py 装配后 202 单测无回归（skills 相关用例）
- [ ] 异步路径等价

## Comments