# 02 — Turn 失败/取消时的 checkpoint finalize

**What to build:** 统一「一轮对话结束态」处理：API 异常、用户 Esc 取消、HITL 放弃时，不留下 `__pregel_tasks` / `branch:to:*` 脏 checkpoint；TUI 切换线程时只 replay 仍 pending 的 HITL。

**Type:** task

**Status:** done

**Blocked by:** —

## 背景

- 已落地（`c682d3a`）：`repair_stuck_thread`、每轮前 repair、400 时 retry。  
- Codex `pending_interactive_replay.rs`：线程 snapshot replay 时过滤已 resolved 的 approval。  
- TUI worker 取消后仍可能留 interrupt 态；与 CLI 管道测试挂死同类。

## 范围

- [x] 审计 `run_agent_turn` / TUI worker：所有异常与 cancel 路径调用 `repair_stuck_thread` 或更强 `finalize_turn(agent, thread_id)`  
- [x] TUI：维护 pending HITL call_id 集合（参考 Codex）；切 session / replay 时不重弹已失效 Modal  
- [x] Esc 取消：显式 abort stream + finalize（避免 orphan Python 进程占 sqlite）  
- [x] 单测：模拟 stuck channel_values → finalize → 下一轮 stream 可成功（可 mock agent）  
- [x] 与 01 联动：`/doctor` 在 finalize 后报告 healthy  

## 非目标

- 不实现 Codex 全量 Event 协议  
- 不做消息 summarization / context 裁剪（另开 phase）  

## 验收

- 手动：故意触发 API 400 后，同 thread 再发「你好」无需 `/delete-session` 即可恢复（或 doctor 自动提示已 repair）  
- 手动：TUI Esc 取消后不卡死、不 ghost Modal  
- pytest 绿；新增 finalize/replay 相关用例  

## 参考

- Codex: `pending_interactive_replay.rs`、`session/session.rs`（单任务可中断）  
- JARVIS: `src/streaming.py`、`src/tui.py`、`src/commands.py`

## Comments

- 2026-08-22：`repair_stuck_thread` 已合并进本票基础，勿重复造轮子。
- 2026-08-22：`finalize_turn` + TUI `_resolved_hitl` / `_hitl_generation` + `run_agent_turn` finally 路径已落地；单测 `test_run_agent_turn_abandon_calls_finalize` 等绿。待人工 smoke Esc/HITL 后关票。

## Resolution

- 实现：`src/commands.py::finalize_turn/turn_needs_finalize/repair_stuck_thread`；接线于 `src/streaming.py` 与 `src/tui.py`（切线程 finalize + pending HITL 过滤 `filter_pending_interrupts`）。
