# TUI 体验七（tui-ux7）：Esc 取消可见性 + 回合串行化门

**Type:** bugfix（用户报告：「已经按 esc，却还是显示"思考中"，不知道是不是真的在思考；后续发消息响应特别慢」）
**Status:** ready-for-agent
**Blocked by:** 无（drain 语义已在 tui-ux6 / ADR-0008 落地，本批是 TUI 侧补强，零上游依赖）

## Problem Statement

tui-ux6 让 Esc 取消「真切断」（ADR-0008 drain：当前 superstep/命令跑完即停）。但取消后的**呈现**与**串行化**仍是缺失的：

1. **取消后 spinner 继续转「思考中...」**：`action_cancel`（`src/tui.py` L1645）worker 活跃分支只写
   `（已取消）` 日志 + `worker.cancel()`，不停 `#status_spinner`。spinner 唯一的停止点在
   `TurnPresenter.run()` finally（`src/tui_turn.py` L206 `_hide_spinner`）——即 drain 收尾**结束**时。
   收尾期间（ADR-0008 语义下可能数秒）spinner 一直显示 `SPINNER_TEXT="思考中..."`
   （`src/tui_format.py:59`），用户无法分辨「还在思考」还是「在取消收尾」。
2. **收尾期间新消息不排队、直接并发**：`_handle_user_message`（L1110）无条件
   `self._worker = self.run_worker(partial(self._stream_agent, ...), thread=True)`——收尾未结束
   就发新消息 → 两个 worker 同时对同一 `thread_id` 跑 `run_agent_turn`/`stream_events`
   → 并发模型调用 + SqliteSaver 锁竞争 + 旧 turn 的 `finalize_turn` 与新 turn 交错 = 「响应特别慢」。

## Solution

两张串行工单（02 blocked 01）：

- **01 取消 banner**：`action_cancel` worker 活跃分支调新增 `JarvisApp._show_cancel_banner()`——
  停 spinner timer、`#status_spinner` 固定 dim 文案「已取消，正在收尾（当前步骤结束后停止）」；
  收尾结束由既有 presenter finally 的 `_hide_spinner` 自动清空（零 presenter 改动）。
- **02 回合串行化门 + 排队**：`JarvisApp` 增 `_turn_gate_threads: set[str]`（收尾/执行中的
  thread 集合）与 `_queued_messages: list[tuple[thread_id, text]]`。被门锁住的消息
  （普通消息/虚拟路径、`/replay`、`/use`、`/undo`）**不清输入、不写日志**，入队 + notify
  「已排队，收尾结束后自动发送」；门释放（presenter finally / undo worker 结束）后自动重投递队首。
  读类 slash 命令与 `/exit` 不进门。会话切换后旧 thread 的排队消息作废并 notify。

## User Stories

1. 作为用户，我按下 Esc 取消后，输入框下方的状态行**立即**变为「已取消，正在收尾…」，
   收尾结束后恢复——我随时知道当前是否还在跑、以及为什么还在跑。
2. 作为用户，我在取消收尾期间发新消息时，它会**排队**并提示我，而不是偷偷并发；
   收尾一结束它自动发出，且**按我发送的顺序**送达，响应不再变慢。
3. 作为用户，收尾期间按双 Esc 撤回，会被明确拒绝（「请等待收尾结束后再撤回」），
   不会出现「撤回+收尾」两个 worker 同时写 checkpoint 的竞态。
4. 作为用户，收尾期间切走会话（新会话/侧边栏切 session），旧会话的排队消息作废并有提示，
   新会话不受旧会话收尾阻塞。

## Implementation Decisions

- **banner 载体 = `#status_spinner` 本身**（不换部件）：`_show_cancel_banner()` 停
  `_spinner_timer`（复用 `_hide_spinner` 的 None-guard 停止模式）、`add_class("-active")` +
  `update("[dim]已取消，正在收尾（当前步骤结束后停止）[/dim]")`。收尾结束 → presenter finally
  `_hide_spinner` 清空。`spinner_style=="none"`（配置）时 `_show_spinner` 是 no-op，banner 同步
  跳过（优雅降级，不崩）。
- **日志 `（已取消）` 保持一条不变**：来源仍是 `action_cancel` 的 `log.write`（UI 线程直写）；
  presenter 侧 `write_line` 在 cancelled 时被抑制（tui_turn L59-61），既有
  `test_escape_cancels_streaming` 断言 `已取消 in joined` 继续成立——banner 测试再加
  `count("已取消")==1`。
- **门键 = thread_id**（不是全局单锁）：会话切换后旧 thread 的 drain 仍在后台线程跑完
  （presenter finally 经 `call_from_thread` 释放），新 session 不能被旧 session 的门锁死；
  排队消息按 thread_id 归属，旧 thread 的门释放时若 `thread_id != app.thread_id` → 丢弃 + notify。
- **门获取点 = 4 个 run_worker 站点**（`/replay`、`/undo`、`/use`、普通消息）；读类 slash
  （`_run_command_worker`）与 `/exit`/`/help`、`/copy` **不获取**。释放点 =
  `TurnPresenter.run()` finally 末尾 `call_from_thread(app._release_turn_gate, turn_thread_id)`
  （`turn_thread_id` 在 run() 入口捕获）+ `_undo_worker` 结束同款。**异常路径也释放**
  （finally 恒执行）；`_release_turn_gate` 内部 `discard` + 按 thread 弹队首重入
  `_handle_user_message`（重入时重新过门检查，此时门已空 → 获取并启动下一轮）。
- **`_handle_user_message` 重排**：门检查（含 vpmapping 计算）**前移**到清输入/写日志之前——
  被排队时输入保留（可再编辑）、日志零重复；门检查通过后才走原有 清输入→写日志→分发 流程。
- **双 Esc 隐式撤回守门**：`_trigger_implicit_undo` 头部检查 `thread_id in _turn_gate_threads`
  → notify 拒绝（不排队——撤回是撤销操作，不能隔轮回放）；空闲且无门时自身获取门
  （与 `/undo` 同 worker 路径，`_undo_worker` 结束释放）。

## Testing Decisions

- **banner 红灯测试**（`tests/test_tui.py` 追加）：慢流 SlowAgent（仿 `test_escape_cancels_streaming`）
  → Esc → `#status_spinner.renderable` 断言 **无「思考中」且 有「已取消」**；drain 结束后再断言
  清空；transcript「已取消」恰好一条。修复前：spinner 是 `spinner_line(...)` 帧（含「思考中」）→ 红。
- **并发度红灯测试**（新 `tests/test_tui_turn_gate.py`）：`ConcurrencyAgent(FakeAgent)` 带
  `inflight`/`max_overlap` 计数 + 慢 `_FakeStream`（interleave 内 6×sleep(0.08)，
  try/finally 里递减 inflight；fake 不抛 GraphDrained，drain = 排空剩余 items）。
  场景：发「第一条」→ 0.15s 后 `action_cancel()` → 立即发「第二条」→ 等全流结束：
  断言 `agent.max_overlap == 1`（修复前 = 2 → 红）+ `agent._calls == 2` + 日志里
  「第一条」序在「第二条」前 + 收尾期间 `agent._calls` 仍为 1（第二条未抢跑、而是排队）。
- **守门/排队的行为测试**（同文件）：
  ① 双 Esc 遇门 → 日志无「正在撤回」（撤回被拒，不启动 `_undo_worker`）；
  ② 收尾期间新会话 → 旧 thread 排队消息作废（`agent._calls` 停 1，不重投递）；
  ③ 排队后自动重投递：门释放后第二条自动发出（与并发度测试同一断言面）。
- 回归面：`tests/test_tui.py` + `test_tui_turn.py` + `test_tui_spinner.py` + `test_streaming.py`
  全绿；全量 pytest 无新增失败（基线 552 绿 + 4 预存/flaky 失败）。
- 纪律：不碰 `tmp_path`；本批纯 TUI 内存态，连自建目录都不需要。

## Out of Scope

- 进程级 SIGKILL 式即时杀（ADR-0008 已定：drain 语义 = 当前命令跑完即停，本批不改语义）。
- 排队消息的 UI 可视化列表（只 notify 计数；`/queue` 之类命令不建）。
- 多会话并行 UI（仍单 thread 视图；门是 thread 级但 UI 不并发渲染多会话）。
- CLI 路径（`--cli`）的串行化（CLI 本就逐条同步等待）。

## Further Notes

- 与 tui-ux6 关系：本批不重复 ADR-0008（drain 已落地，commit 3bbc5f8）；01 解决「看不见收尾」，
  02 解决「收尾期并发」，两者互补：banner 告诉用户「为什么还能再等一会儿」，门保证「等等也不会更慢」。
- 假设（diagnosing-bugs Phase 3 根因，写进 commit 信息）：**H1** 无守护 `run_worker` →
  同 thread 双 graph 并发（慢响应直接原因）；H2 SqliteSaver 锁竞争、H3 模型限流退避（次级放大）。
- 仓库强制要求：参考开源（opencode 取消后有「cancelled」状态行、codex 排队提示）；
  deepagents/langgraph 无新 API（RunControl 已在 tui-ux6 用过）。
