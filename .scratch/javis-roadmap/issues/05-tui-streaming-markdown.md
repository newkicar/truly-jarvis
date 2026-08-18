# 05 — TUI 逐 token + Markdown 同屏流式

**What to build:** TUI 中 AI 回答在生成过程中即可阅读：token 逐步出现的同时保持 Markdown 结构可读（标题、列表、代码块等），而不是仅显示「思考中」再在段末整块替换。Esc 取消行为与现有流式 worker 兼容。

**Blocked by:** 04 — Inbox 边界 ADR 与设计文档同步

**Status:** done

- [ ] 流式过程中 RichLog 增量更新 Markdown 渲染（或节流重渲染），用户可边看边等
- [ ] 段结束时的最终展示与流式过程视觉一致，无重复标题或闪烁
- [ ] Esc 取消后状态清晰（已有「已取消」提示保持或增强）
- [ ] 单测或 `run_test` 冒烟：假 agent 流式输出时消息区有中间态内容
