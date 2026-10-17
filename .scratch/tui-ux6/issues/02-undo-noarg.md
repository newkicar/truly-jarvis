# 02 — /undo 无参化（只撤最近一条，多轮靠反复调用）

**What to build:** 命令面去 N：
- `src/commands.py`：`_HELP_COMMANDS` L41（`/undo` 撤回最近 1 条用户消息（仅消息层；多轮请反复调用））、L64 提示行同改、`dispatch_command` L1152-1158 —— `/undo` 带任何参数 → 返回提示「用法: /undo（无参）；/undo 只撤回最近 1 条，多轮请反复调用」**不执行**。
- `src/tui.py` L1110-1123 特判同款（提示、不执行）；`_undo_worker`/双 Esc 路径保持 n=1 不变。
- `src/slash_completion.py` L26：`SlashCommand("/undo", "/undo", "撤回最近 1 条用户消息（多轮反复调用）")`。
- `tests/test_tui.py` 中 `/undo abc` 断言文案同步（原「用法: /undo [N]」→ 新提示文案）。
- 内核 `commands.undo(agent, tid, n=1)` 签名保留（测试与内部仍可用 n）。

**Type:** task
**Status:** done (2026-10-18, commit e592c5b)
**Blocked by:** 01

## 验收
- [x] CLI/TUI：`/undo` 撤一轮；`/undo 3` 给提示且不执行
- [x] slash 补全、HELP、双 Esc 文案全部无 N 语义
- [x] test_tui.py 更新后全绿（test_tui+test_commands 95 绿，含 /undo abc 新文案断言）

## Comments
用户原话：「undo命令只要撤回最近一次对话就可以了，后面不需要有参数，如果用户需要回撤多轮对话，只要反复使用该命令就可以了。关键是对话回撤这个功能的稳定性」——稳定性由 01 保证，本票只改命令面。
