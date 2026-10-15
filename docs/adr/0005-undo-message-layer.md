# ADR-0005: /undo 消息层撤回（time travel）

**状态:** 已接受（2026-10-15）

## 背景

误发消息（如输入一半误按回车）后，TUI 只能 Esc 停止执行，但发出去的那条用户消息无法撤回；codex 支持多按 Esc 回退（backtrack 状态机），opencode 有 /undo。仓内 checkpoint 基建（get_state_history / update_state / boundary_checkpoints / finalize_turn）已齐，缺一个面向「误发消息」的回撤入口。

## 决策

1. **`/undo [N]`（CLI + TUI，默认 N=1）= 消息层撤回**：把线程头回退到「第 N 个（从新数）input checkpoint 的父 checkpoint」，即回到该用户消息发出**之前**的状态。纯消息层，**不动文件/Inbox**（文件层归 `/rollback` + `/replay`，职责不重叠）。
   - 实现原语与 `finalize_turn` 同款：`agent.update_state(thread_config(tid, parent_cid), None)`。
   - 边界：撤到会话第一条消息之前 = 外科式消息删除（head 上 RemoveMessage 最后一条 HumanMessage 及其后全部消息，`as_node="model"`，与 fork 先例一致）；允许撤成空白会话（thread_id 保留）。
   - 撤掉的 turn 若含未决 HITL 中断，随 checkpoint 一并作废（TUI 侧先走 `_bump_hitl_generation`/`_mark_hitl_resolved` 清理舞蹈）。
2. **TUI 交互（对标 codex prime）**：空闲态（无流式 worker、无 Modal）单按 Esc 只出提示横幅「1.5s 内再按 Esc 撤回上一轮」；1.5s 内第二下 Esc = `/undo 1`；任何输入取消提示。退出仍走 ctrl+q / ctrl+c（空闲 Esc 不再退出）。
3. **transcript（对标 codex 裁剪 scrollback）**：undo 成功后 TUI 对话区整体重建（clear + 按会话状态重渲染 + 一行「已撤回 N 条消息」横幅），不留被撤回轮次的残留。

## 被否决的选项

- **codex 完整 backtrack overlay**（逐字稿预览导航、source-preserving 分支）：交互成本高；`/history` + `/replay` + `/fork` 已覆盖浏览/分叉，本期只做「撤回误发消息」的最小闭环。
- **/undo 连带文件回退**：与 /rollback 语义纠缠、误伤用户手动改动；撤回文件是明确需求时组合 `/undo` + `/rollback` 即可。
- **空闲单 Esc 直接 undo**（无 prime）：误触代价太高（一次 Esc = 撤销上一轮），prime 二次确认更稳。

## 影响

- 新增：`commands.undo`、`/undo` 进 SLASH_COMMANDS 与 TUI 分发；TUI Esc prime 状态机（JarvisApp）。
- 测试：undo 各边界（N 轮 / 撤到空白 / HITL 悬挂 / 无 input checkpoint）+ TUI 双击 Esc。
- 文档：CONTEXT.md「撤回」词条；README 命令表。