# 08 — TUI 侧边栏会话列表

**What to build:** TUI 增加可折叠侧边栏，列出非 `sched-*` 的会话 thread_id，点击切换当前会话（等同切换 thread 后继续对话）。不替代 `/sessions` 等命令，但提供 opencode 式扫读体验。

**Blocked by:** 07 — @ 文件路径补全

**Status:** done

- [x] 侧边栏从 checkpointer 或现有 `list_sessions` 逻辑拉取会话列表
- [x] 选中项高亮当前 thread；切换后 Header sub_title 更新
- [x] 布局：消息区缩窄，小屏可隐藏侧边栏（快捷键或按钮）
- [x] 单测：切换会话后 `thread_id` 变化、消息区可继续输入
