# 09 — /use + /skills + catalog manual_only + /doctor 列

**What to build:** skill_discovery：SkillMeta 加 `manual_only: bool`、`fs_path: Path`（frontmatter `disable-model-invocation: true` → manual_only；层覆盖语义与原生 last-one-wins 对齐）；新 `build_skill_use_message(config, name, extra="")`：catalog casefold 查；None → 返回 None（调用方列可选名）；读 fs_path utf-8、剥 frontmatter（复用 _FRONTMATTER_RE）→ `"[skill:name] 完整指令…" + （extra 时）任务段`，作为本轮 user 消息注入；TUI `_handle_user_message` 特判 `/use` + 新命令 `/skills`（manual 打 [manual]，模型可见 skill 也可 /use）；CLI main.py 输入循环前置拦截 /use（转 build_skill_use_message 后按普通用户消息 _stream_turn）；/doctor skills 表加 manual_only 列；slash_completion SLASH_COMMANDS 补 /undo、/skills、/use。

**Type:** task
**Status:** open
**Blocked by:** 无

## 验收
- [ ] /use manual skill：注入 SKILL.md 全文（无 frontmatter）为 user 消息
- [ ] /skills 列表正确；disable-model-invocation 项带 [manual]
- [ ] /use 查无此名 → 报错 + 可用名清单
- [ ] /doctor skills 表加列；补全含三新命令；单测齐

## 参考
ADR-0007。原生 deepagents 有 pinned_skills 官方机制，但 JARVIS 自建 /use 更贴命令层（ADR 已定）。

## Comments