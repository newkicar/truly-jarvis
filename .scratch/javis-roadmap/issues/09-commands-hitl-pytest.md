# 09 — 命令分发与 CLI 审批单测补全

**What to build:** pytest 覆盖 `dispatch_command` 主要子命令（含 `/replay`、`/fork`、`/rollback` 与 Inbox 回退文案）及 CLI `_handle_interrupts` 的 `e`（编辑参数）与 `a`（always approve）路径。全部使用 FakeAgent / 假输入，不触网，可进 CI。

**Blocked by:** 08 — TUI 侧边栏会话列表

**Status:** done

- [x] `tests/test_commands.py` 补 `/replay`、`/fork`、`/rollback`（含 Inbox 清单输出断言）
- [x] `tests/test_hitl.py` 或等价：CLI `e` 返回 edited_action、`a` 更新 permission_state 且写回 javis.json（tmp path）
- [x] 全量 pytest 绿；不新增 CI 真模型依赖
