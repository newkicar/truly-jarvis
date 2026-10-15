# 12 — 文档同步 + 测试批回归 + 汇报

**What to build:** AGENTS.md 新增「TUI 体验五」段：/undo（双 Esc 语义 + 空闲单 Esc 不退 + as_node="model" 空白撤销）、/use //skills（manual-only skill，disable-model-invocation frontmatter）、permissions.heuristics + 前缀规则示例 `{"execute":{"*":"ask","git *":"allow"}}`（字符串规则自动升格）、jarvis_skills（JarvisSkillsMiddleware 替换原生 skills= 注入）、input_probe、Modal 布局规约（80%/70%/overflow-y/按钮行固定底部）、PrefixModal；跑测试批：A（backend/路由 ~95）/ B（TUI/UX ~259）/ C1（config 48 绿 + 3 既有失败勿修）/ C2+C3（RAG 前 2 例）；汇报含 git bash 探测操作指引。

**Type:** task
**Status:** open
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11

## 验收
- [ ] AGENTS.md 段落落盘
- [ ] 测试批全绿（C1 三处既有失败除外：absolutizes_paths / parses_mcps_dict / obsidian_vault 回退）
- [ ] 汇报交付：5 功能说明 + 新命令用法 + jarvis.json 新键 + input_probe 回传指引

## Comments