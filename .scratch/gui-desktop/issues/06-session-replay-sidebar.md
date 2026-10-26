# 06 — 会话侧栏 · AI 命名 · 改名 · 全量回放

**What to build:** 左侧会话侧栏：条目 = 摘要（首条用户消息截 18 字，空回落 thread_id），当前会话高亮，「＋ 新会话」；`sched-*` 过滤。会话切换/重启 app 后重建该会话记录时**完整回放工具调用记录**（TUI 已知问题②在 GUI 不复制：从检查点消息重建 user/AI 文本 + 工具行——AIMessage.tool_calls × ToolMessage 按 tool_call_id 配对，输出与错误态齐全，工具行默认折叠带「＋ 详情」）。命名 = 05 的 sessions.json 短名优先于摘要。

**Blocked by:** 01（GUI 运行时骨架）、03（对话区与输入区）

**Status:** ready-for-agent

- [ ] 切会话再回来、以及重启 app 再进旧会话，工具调用记录都在（offscreen 双实例回放断言，原型实证手法）
- [ ] 侧栏摘要/命名显示正确（有 sessions.json 用短名，无则摘要）
- [ ] 当前会话高亮 + 新会话即入栏
- [ ] 既有 200+ 单测全绿（回放走 get_state 只读路径，不改检查点写入）
