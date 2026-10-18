# 02 — 回合串行化门 + 排队（收尾期新消息排队，不并发）

**What to build:** 收尾期（drain 未结束）发新消息时，`_handle_user_message`（src/tui.py L1110）无条件 `run_worker` → 两个 worker 对同一 `thread_id` 并发跑 `run_agent_turn`/`stream_events` → 并发模型调用 + SqliteSaver 锁竞争 + 旧 turn 的 `finalize_turn` 与新 turn 交错（「响应特别慢」根因 H1）。加 thread 级回合门 + FIFO 排队：

- `__init__`（state fields 块末、`self._cmd_newline_hinted` L870 之后）：
  - `self._turn_gate_threads: set[str] = set()`（执行/收尾中的 thread 集合）
  - `self._queued_messages: list[tuple[str, str]] = []`（(thread_id, 原始 raw text) FIFO）
- `_handle_user_message` 重排：`vpmapping = commands.virtual_path_mappings(self.config)` 计算前移到清输入/写日志**之前**；门检查紧随其后。被锁定的门（`self.thread_id in self._turn_gate_threads`）的命中条件：普通用户消息（含虚拟路径引用）+ `/replay` + `/use` + `/undo`——即 `text.startswith("/") and not commands.is_virtual_path_reference(text, vpmapping)` 时仅当命令是这 3 个之一才进门（`/exit`、`/help`、`/copy` 及其它走 `_run_command_worker`（L1173）的读类 slash 命令**不进门、不排队**）。
  - 命中且门已锁：`self._queued_messages.append((self.thread_id, text))`；`self.notify(f"上一轮取消收尾中，已排队 {N} 条，收尾结束后自动发送", timeout=2)`（N = 本 thread 当前排队数）；**直接 return——不清输入、不写日志**（重入不重复）。
  - 门获取点 = 4 个 `run_worker` 站点各自之前：`/replay`（L1145 附近）、`/undo`（L1155）、`/use`（L1167）、普通消息（L1187）：`self._turn_gate_threads.add(self.thread_id)`。早退错误分支与读类命令不获取。
- 门释放：
  - `TurnPresenter.run()`（src/tui_turn.py L170-214）：run() 入口（L172 `self.worker = get_current_worker()` 之前）捕获 `turn_thread_id = self.app.thread_id`；finally 末尾（现有 `_hide_spinner`/`_refresh_todos_panel` 调用之后）加 `self.app.call_from_thread(self.app._release_turn_gate, turn_thread_id)`。异常路径 finally 恒执行 → 也释放。
  - `_undo_worker`（L1207，`self.call_from_thread(self._apply_undo_result, ...)` 之后）：`self.call_from_thread(self._release_turn_gate, self.thread_id)`。
  - 新增 `JarvisApp._release_turn_gate(tid)`（UI 线程）：`self._turn_gate_threads.discard(tid)`；若 `tid != self.thread_id`（会话已切走）→ 丢弃 tid 全部排队项 + `notify(f"会话 {tid} 有 {N} 条排队消息因会话切换未发送", timeout=3)`；否则弹 tid 队首（FIFO）重新入 `self._handle_user_message(raw)`（重入时门检查重跑，此时门已空 → 获取并启动下一轮）。
- 双 Esc 隐式撤回守门：`_trigger_implicit_undo`（L1239）头部 `if self.thread_id in self._turn_gate_threads: self.notify("上一轮取消收尾中，请等待收尾结束后再撤回", timeout=2); return`（撤回不排队——撤销操作不能隔轮回放）；空闲且无门时正常获取门（与 `/undo` 同 worker 路径，`_undo_worker` 结束释放）。
- 红灯测试（新 `tests/test_tui_turn_gate.py`；import `from tests.test_tui import FakeAgent, _FakeStream, _FakeMsg, _type_and_enter` + 自身需要的 `CopyableRichLog`/`Static` 等）：
  - `ConcurrencyAgent(FakeAgent)`：`inflight=0; max_overlap=0`；`stream_events` 增 inflight、`max_overlap=max(...)`、返回自定义 `_FakeStream` 子类（`interleave()` 内 `for i in range(6): time.sleep(0.08); yield ("messages", _FakeMsg(f"seg{i}"))`，`try/finally` 里递减 inflight；fake 流不抛 `GraphDrained`，取消 = 排空剩余 items，正常结束）。
  - ① 并发度（修复前 RED）：发「第一条」→ `asyncio.sleep(0.15)` → `app.action_cancel()` → pause → 立即 `_type_and_enter(pilot, "第二条")` → 断言 `agent._calls == 1`（第二条已排队未抢跑）→ sleep 1.5 + pause → `agent.max_overlap == 1`（修复前 = 2 → 红）+ `agent._calls == 2` + 日志「第一条」在「第二条」之前。
  - ② 双 Esc 遇门拒绝：收尾中连续两次 `action_cancel()` → 日志无「正在撤回」（`_undo_worker` 未启动）。
  - ③ 会话切换作废旧队：取消 → 发「第二条」（入队）→ `app.action_new_session()` → 等待门释放 → `agent._calls` 恒为 1（旧 thread 排队消息被丢弃且 notify，不重投递）。

**Type:** bug
**Status:** ready-for-agent
**Blocked by:** 01（banner 先行，实施顺序 01 → 02）

## 验收
- [ ] 并发度红灯绿（`max_overlap == 1`；排队消息不抢跑，FIFO 重投递无重复日志）
- [ ] 双 Esc 遇门拒绝（日志无「正在撤回」）+ 会话切换作废旧 thread 排队消息
- [ ] 读类 slash / `/exit` / `/help` / `/copy` 不受门影响（既有测试无回归）
- [ ] 全量 pytest 无新增失败（基线 552 绿 + 4 预存/flaky 失败）

## Comments
