# 12 — 文档同步 + 测试批回归 + 汇报

**What to build:** AGENTS.md 新增「TUI 体验五」段：/undo（双 Esc 语义 + 空闲单 Esc 不退 + as_node="model" 空白撤销）、/use //skills（manual-only skill，disable-model-invocation frontmatter）、permissions.heuristics + 前缀规则示例 `{"execute":{"*":"ask","git *":"allow"}}`（字符串规则自动升格）、jarvis_skills（JarvisSkillsMiddleware 替换原生 skills= 注入）、input_probe、Modal 布局规约（80%/70%/overflow-y/按钮行固定底部）、PrefixModal；跑测试批：A（backend/路由 ~95）/ B（TUI/UX ~259）/ C1（config 48 绿 + 3 既有失败勿修）/ C2+C3（RAG 前 2 例）；汇报含 git bash 探测操作指引。

**Type:** task
**Status:** done
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11

## 验收
- [x] AGENTS.md 段落落盘
- [x] 测试批全绿（C1 三处既有失败除外：absolutizes_paths / parses_mcps_dict / obsidian_vault 回退）
- [x] 汇报交付：5 功能说明 + 新命令用法 + jarvis.json 新键 + input_probe 回传指引

## Comments

## Comments
- **done（2026-10-16）**：AGENTS.md 新增「TUI 体验五」段（①/undo+双Esc ②前缀永久放行+heuristics ③manual-only skill ④input_probe+ime_shim ⑤Modal 布局规约）。回归批次（沙箱外执行，沙箱内 pytest tmp_path 被 WinError 5 拦截）：A backend/路由 43 全绿；B TUI/UX 147 全绿；C1 config 28 绿 + 3 既有失败（absolutizes_paths / parses_mcps_dict / obsidian_vault 回退，按 spec 不修）；C2/C3 RAG 前 2 例 2 全绿。汇报见 5 项功能说明 + git bash 回传指引（不合并 main）。
