# TUI 体验六（tui-ux6）

**Type:** enhancement + bugfix
**Status:** done (2026-10-18)

## 背景（用户报告 4 项 + 定稿决策）

1. **A（新需求）输入框无换行能力**：Shift+Enter 无效，输入框（Textual `Input` 单行）完全没有换行/多行输入。定稿：continuation buffer 方案——Shift+Enter（+ 退路 Ctrl+J）把当前行压入已确认续行（dim 堆叠显示在输入框上方），提交时 `\n` 拼接；`/` 命令行不支持换行（Shift+Enter 直接提交+提示一次）；空行+Backspace 弹回末条续行。粘贴多行取首行的旧行为**本批不动**。
2. **B（bug）Esc 取消不立刻切断**：worker 取消只置 `is_cancelled` 标志，`consume_stream_events` 在事件到达时才检查 → 慢工具（execute 长命令）期间图继续跑。定稿：`langgraph.runtime.RunControl` drain——每个 stream 尝试新建 `RunControl()` 传入 `stream_events(..., control=)`；取消命中先 `request_drain("user-cancel")` 再继续排空（GraphDrained 上抛、后续 superstep 跳过）。**语义（汇报需写清）：正在执行的当前命令跑完后停止，后续步骤被跳过，不是 SIGKILL 式即时杀死。**
   红/绿证据（`scratch/probe_drain.py`）：noctrl 跑满 2.57s（取消无效）；drain 0.51s 抛 `GraphDrained`。
3. **C（bug）undo 第二次起报错**：根因已定位并红确认——`src/commands.py:23 thread_config()` 的 configurable 缺 `checkpoint_ns`；langgraph 1.2.11 `update_state`→`checkpointer.put` 强制读 `config["configurable"]["checkpoint_ns"]` → `KeyError`。红证据：`scratch_repro_undo.py` undo #1 即 KeyError。定稿：`thread_config` 补 `"checkpoint_ns": ""`（L23 唯一出处，覆盖 undo/_rollback/fork/replay/finalize_turn 全链路）；新增三轮对话 undo×3 循环回归测试（SqliteSaver + 自建目录，禁 tmp_path）。
4. **D（需求澄清）/undo 无参化**：`/undo` 只撤最近一条用户消息、**不带 N 参数**；多轮回撤 = 反复调用。内核 `commands.undo(agent, tid, n=1)` 保留 n（内部/测试用）；命令面（CLI dispatch、TUI 特判、slash 补全、HELP 文案）去 N，带参数时给提示且不执行。关键诉求 = 撤回稳定性（C 修好后 D 自然成立，02 blocked 01）。

## ADR
- `docs/adr/0008-cancel-drain-semantics.md`（B 的 drain 语义定稿）

## 方案（工单 01–04，实施顺序即编号）

### 01 — C：checkpoint_ns 全链路修复
- `src/commands.py` `thread_config`：configurable 补 `"checkpoint_ns": ""`。
- `scratch_repro_undo.py` 转绿（3 轮对话 + undo×3 撤到空白，无异常）。
- 回归测试 `tests/test_undo.py` 新增：三轮对话循环 undo 至空白 + 空白后继续 undo 返回「没有可撤回」（不抛异常）；SqliteSaver + `tempfile.gettempdir()+os.makedirs` 自建目录纪律。

### 02 — D：/undo 无参化（blocked 01）
- `commands._HELP_COMMANDS` L41、L64 提示行、dispatch L1152-1158（带 N → 提示「/undo 无参；多轮请反复调用」不执行）；TUI 特判 L1110-1123 同款；`slash_completion.py` L26 去掉 `[N]`；tests 断言文案同步。

### 03 — B：Esc 真切断（RunControl drain）
- `run_agent_turn`/`_run_stream`：每个 stream 尝试 `RunControl()`，`stream_events(..., control=control)`。
- `consume_stream_events` 增 `control` 参：取消命中 → `on_cancelled()` + `request_drain("user-cancel")` + 抑制后续回调继续排空；`GraphDrained` 自然上抛。
- `_stream_with_resilience`：`except GraphDrained` 不重试、不 cleanup 上抛；`run_agent_turn` catch `GraphDrained` → `outcome="cancel"` 返回 False（finally 走 finalize_turn，不 handoff）。
- TUI 侧零改动：取消时 run_agent_turn 正常返回 False，`tui_turn` finally 写「（已取消）」。
- 测试：fake 慢工具 + control drain（单测 consume 层 request_drain 断言 + e2e wall-time 断言「只跑一次慢工具、不进入第二次模型调用」）。ADR-0008。

### 04 — A：Shift+Enter 多行输入
- pilot 探针 `scratch/probe_shift_enter.py`（`app.run_test()` + `pilot.press("shift+enter")`，确认 Textual 层修饰键可达；真实 ConPTY 透传与否需用户实测回传，Ctrl+J 退路常备）。
- 实施：`PasteInput` BINDINGS 增 `shift+enter`/`ctrl+j` → `action_newline`；app 侧 `_continuation: list[str]` + `#continuation` dim Static（堆叠显示）；提交拼接 `\n`（`/` 行禁用换行+一次提示）；空输入 Backspace 弹回末条续行；`on_input_submitted` 清空续行。
- 测试：run_test 场景（两行提交拼接 / ctrl+j 同义 / /命令不换行 / backspace 弹回）；AGENTS.md「TUI 体验六」段 + 全量回归。

## 验收
- [x] 4 张工单全 done、各 1 commit（`fix(tui):`/`feat(tui):` 中文）
- [x] C 红转绿 + 回归测试（多轮 undo 循环稳定）
- [x] D 命令面去 N、内核保留
- [x] B 探针红/绿对照 + 单测（drain 后只跑一次慢工具）
- [x] A pilot 探针 + TUI 测试；真实终端 Shift+Enter 需用户实测（汇报中注明）
- [x] 全量 pytest 绿（自建目录纪律；既有预存失败不新增）

## 回归批次（归档确认，2026-10-18）
- commit 对照：01=`c40d6a9` / 02=`e592c5b` / 03=`3bbc5f8` / 04=`903ed3c`。
- 全量 pytest（`--ignore=tests/test_rag.py`，该模块 chromadb 原生层 Windows access violation 崩溃中断全量跑，单独跑不受影响）：**552 passed, 4 failed，无 04 新增失败**：
  - `tests/test_config.py` 3 条失败为预存（`3bbc5f8` 上复跑同样 3 failed / 14 passed，与 04 无关）；
  - `test_streaming.py::test_run_agent_turn_drain_stops_after_single_slow_tool` 为时序 flaky（重载全量跑偶发失败，单跑 3/3 绿，不修）。
- 04 专属：`tests/test_tui.py` 4 场景全绿；pilot 探针 `scratch/probe_shift_enter.py` PASS（Textual 层）；真实 ConPTY/PowerShell shift 透传待用户实测回传（Ctrl+J 常绑退路）。
