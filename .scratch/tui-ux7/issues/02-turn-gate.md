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
**Status:** done (2026-10-18, commit 4ae094f)
**Blocked by:** 01（banner 先行，实施顺序 01 → 02）

## 验收
- [x] 并发度红灯绿（`max_overlap == 1`；排队消息不抢跑，FIFO 重投递无重复日志）
- [x] 双 Esc 遇门拒绝（日志无「正在撤回」）+ 会话切换作废旧 thread 排队消息
- [x] 读类 slash / `/exit` / `/help` / `/copy` 不受门影响（既有测试无回归）
- [x] 全量 pytest 无新增失败（基线 552 绿 + 4 预存/flaky 失败）

## Comments
2026-10-18 实施（commit 4ae094f）：
- 改动：`src/tui.py`（`_turn_gate_threads`/`_queued_messages` 状态字段；`_handle_user_message` 门检查重排 + 4 个 run_worker 站点入门（/replay、/undo、/use、普通消息）；`_trigger_implicit_undo` 门守卫；新增 `_release_turn_gate`（UI 线程，会话切换作废旧队列 + notify，否则 FIFO 重投队首））；`src/tui_turn.py`（`TurnPresenter.run` 入口捕获 `turn_thread_id`，finally 恒经 `call_from_thread` 释放门）；`_undo_worker` 结束释放门。
- NoMatches 防御（本批附带，消除间歇 `WorkerFailed` 与 drain 流式测试 flaky）：`src/tui.py` 的 `call_from_thread` 驱动 UI 写路径（`_show_ai_stream`/`_update_ai_stream`/`_hide_ai_stream`/`_hide_spinner`/`_refresh_todos_panel`）统一 `try/except NoMatches: return`（Textual 8.x 中 `NoMatches` 在 `textual.css.query`）。
- 测试：新 `tests/test_tui_turn_gate.py`（3 条轮询型：`test_queue_serializes_turns_during_drain` / `test_double_esc_during_drain_no_implicit_undo` / `test_new_session_drops_queued_message`，drain 窗口 8×0.15s、取消于流启动后 ~0.2s，断言全部轮询可观测状态）。
- 结果：gate 单文件 3/3 绿；5 文件组合 65 绿 × 8 轮 0 失败；全量 557 绿 + 4 预存/flaky 失败（同基线，无新增）。

diagnosing-bugs 六阶段痕迹（本批共享）：
- Ph1 假设：H0 spinner 未 stop 致「思考中」残留；H1 无守护 run_worker → 同 thread 双 graph 并发（慢响应直接原因）；H2 SqliteSaver 锁竞争；H3 模型限流退避（次级放大）。
- Ph2 RED：banner 测试见 spinner `⠸ 思考中...`；gate 测试首断言 `agent._calls == 2` / `max_overlap == 2`（修复前并发 = 2）。
- Ph3 根因确认 = H1（同 thread 双 graph 并发 → SqliteSaver 锁竞争 + finalize_turn 交错）。
- Ph4 GREEN：3 gate + 2 banner 测试全绿。
- Ph5 回归：5 文件组合（test_tui / test_tui_turn_gate / test_tui_turn / test_tui_spinner / test_streaming）65 绿 × 8 轮 0 失败；全量 557 绿 + 4 预存/flaky 失败（3× test_config 预存 + 1× test_streaming drain 慢工具 flaky，与本批 NoMatches 防御同根因，单跑 2/2 通过）无新增。
- Ph6 教训：回合级资源（worker / graph / checkpoint 写）必须 thread 级串行化门守护；drain 语义下「取消 ≠ 线程立即死亡」，UI 呈现（banner）与逻辑（门）需配套；worker 线程 UI 写必须对节点生命周期容错（NoMatches，Textual 8.x 在 `textual.css.query`），否则 drain/FIFO 时序下间歇 WorkerFailed；测试时序用轮询可观测状态，不用固定 sleep 对齐窗口。

