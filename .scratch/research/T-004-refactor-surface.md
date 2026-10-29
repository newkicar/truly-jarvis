# T-004 · 事件边界最小重构面（读本仓）

> 研究子代理产出 · 2026-10-26 · 代码基准 = GUI worktree（feat/gui-desktop）`src/` 副本。
> 验收线：**TUI 零改动**（既有测试全绿）。本文结论：既有 `src/` 文件 0 行必改；GUI = 第三客户端，按同一条契约接入。

## TL;DR

- **事件边界已经是客户端无关的**。`src/streaming.py` 与 `src/commands.py` **无 Textual import**（streaming.py 全文件 0 个 UI 依赖；commands.py 头注自述「不依赖终端交互」，仅 commands.py L130 一处 `render_markdown` 返回 rich 对象供 TUI RichLog 用——GUI 可不用它）。CLI 已是「第二个客户端」先例，GUI 是第三个。
- **HITL resume 契约客户端无关**：`collect_interrupt_decisions(ask_action)` 只要求 `ask_action: inv → dict|None`；TUI modal 与 `cli_prompt_action` 返回**同构 dict**（docstring 原文「返回 modal 同构结果 dict」），最终形状 `{"decisions": [...]}` 交 langgraph 原生 `Command(resume=)`。GUI 只需新增第三个 `ask_action` 实现。
- **最小重构面 = 0 必改 + 新增 `src/gui/` 包 4 个文件**（presenter / ask_action / 回合门 / 装配），全部是「照抄 tui 形状、换事件泵」的平移，不是对既有代码的重构。
- **必须「重写」的只有 TUI 渲染层**，且它不需要被重写——它不迁移到 GUI，GUI 用自己的呈现层。Textual 专属文件（tui.py / tui_turn.py / tui_log.py / tui_punct.py / ime_shim.py / input_probe.py）保持原样、划出 GUI 边界。
- 架构提案：MVP 选 **A：GUI 进程内跑 graph**（与 TUI 同构，线程模型照抄），事件通道 = 复用 5 键 `StreamCallbacks` + `run_agent_turn` 的 4 个 `on_*` 参数，不发明新协议；**B：独立 runtime worker 进程** 留作「桌面端多开/崩溃隔离」升级路径。

## GUI 可直接挂（零重构）部分清单

### streaming.py —— 整文件可直接用（0 行改）

| 符号 | 说明 |
|---|---|
| `run_agent_turn(agent, thread_id, user_input, *, checkpoint_id, handle_interrupts, callbacks, is_cancelled, on_fallback_message, on_stream_start, on_cancelled, on_turn_incomplete)` | 单回合驱动：内部 `sync_permission_context` + `set_current_thread_id`（成对清理）、50ms drain 看门狗（`_DRAIN_WATCHDOG_INTERVAL_S`）、`GraphDrained`/`GraphRecursionError`/图片 auto 回落分支、`force_handoff` 到顶交接。参数全是 callable，无一 UI 类型 |
| `consume_stream_events(stream, callbacks, *, is_cancelled, on_cancelled, control)` | `stream_events(v3)` interleave 消费循环（含 tui-ux6 drain 语义）。回调键 5 个：`on_subagent` / `on_tool_call` / `on_message_delta` / `on_message_end` / `on_status`（`StreamCallbacks = dict[str, Callable]`，L17） |
| `collect_interrupt_decisions(interrupts, ask_action, *, permission_state, on_always_approve)` | 逐条中断收集，返回 `{"decisions": [...]}` 或 None（放弃本轮） |
| `cli_prompt_action(inv, *, permission_state, input_fn, on_always_approve, vault_path, workspace_root)` | 第一参考实现（终端版 ask_action），返回与 modal 同构 dict |
| `decision_from_choice` / `interrupt_action_key` / `filter_pending_interrupts` / `format_agent_error` / `iter_text_deltas` | 纯函数，客户端无关 |

**Textual 耦合点核实（工单点名项）**：`streaming.py` 中 `call_from_thread` 出现次数 = 0；HITL 推送通过 `handle_interrupts`/`ask_action` **回调注入**，推送方向是「worker 线程回调宿主」，宿主是谁由调用方决定。耦合不在 streaming，在 tui_turn/tui（见下）。

### commands.py —— 整文件可直接用（0 行改）

60+ 符号全部纯逻辑（本 worktree 实测清单）：`thread_config`（L23，`{"configurable": {"thread_id", "checkpoint_ns": ""}}` 唯一出处）；`ToolInvocation`（dataclass）；`dispatch_command`；`finalize_turn`/`turn_needs_finalize`/`channel_values_stuck`；`force_handoff`；`undo`/`fork`/`prepare_replay`/`completed_turn_checkpoint`/`repair_stuck_thread`；`yolo_command_text`；`always_approve`；`build_submission`（提交纯函数）；`render_session_text`/`list_sessions`/`resolve_session_target`；`format_doctor_report`；`first_human_text` 等。GUI 的菜单/命令面板直接调 `dispatch_command`。

### 其余可原样复用模块

| 模块 | 符号 | 备注 |
|---|---|---|
| permissions.py | `GATED_TOOLS`、`build_permission_interrupts` → `(interrupt_on, state)`、`_build_interrupt_on`、`apply_permission_override`、`approve_prefix`、`yolo_on/off/active`、`PermissionDenyMiddleware` | 全 gated 工具 decisions 已统一 `["approve","reject","edit"]`（tui-ux11）；state 按引用共享、live 生效 |
| agent.py | `build_agent`（L280） | 装配段直接调 |
| resilience.py | `ToolErrorBoundaryMiddleware`/`DoomLoopMiddleware`/`NoProgressGuardMiddleware`/`StepBudgetMiddleware` 等 | 全在 graph 内部，与客户端无关 |
| jump_in_queue.py | `JumpInRegistry`（L21）、`set_current_thread_id`（L124）、`MessageQueueJumpInMiddleware` | 进程内；跨进程注意见风险⑤ |
| scheduler.py | `make_scheduler`（L249） | 进程内；跨进程注意见风险⑤ |
| mcps.py | `load_mcp_tools` | 启动时一次性加载，客户端无关 |
| tui_format.py | 全部 | 头注「CLI+TUI 共用纯函数」，import rich（非 Textual），GUI 可借用消息排版纯函数或弃用（GUI 自带渲染） |

### HITL resume 决策结构（工单点名 `{"decisions": [...]}`）

形状链已闭环且客户端无关：`interrupts → collect_interrupt_decisions → {"decisions": [...]}` → `Command(resume=…)`（langgraph 原生 interrupt/resume 契约）。GUI 的 `ask_action` 实现返回同构 dict 即接入完成；「放行/永久放行/拒绝/编辑参数/前缀放行」全语义经 `decision_from_choice`/`apply_permission_override`/`approve_prefix` 复用，**GUI 对话框按钮可以比 TUI 少（MVP：放行/拒绝/编辑），契约不变**。

## 重构点清单（文件/函数级）

**结论：既有文件必改 = 0。以下为 GUI 新增面（新文件，不动既有）：**

### 新增 `src/gui/` 包（MVP 四文件）

| 新文件 | 形状参照 | 为什么必须动（新增） | 最小改法 |
|---|---|---|---|
| `gui_presenter.py` | `tui_turn.py::TurnPresenter`（L5-153：`__init__` 捕获 `thread_id`/`permission_state`/`config`；`callbacks()` 返回 5 键 dict；`handle_interrupts` 内 `ask_action = app.call_from_thread(app._wait_modal_dismiss, inv)`） | TurnPresenter 的 ~20 处 `app.call_from_thread(...)`（L48/63/70/76/80/90/114/122/139/145/151）是 Textual 耦合核心——worker 线程编组进 UI 线程的唯一通道 | 同构类，唯一替换 = `call_from_thread(fn,*a)` → GUI 事件泵（Qt：`signal.emit(fn,a)` + 事件循环；或 `queue.Queue` + `app.after`）。`callbacks()`/`handle_interrupts` 签名不变 |
| `gui_hitl.py` | `tui.py::_wait_modal_dismiss`（L1931 起）+ `cli_prompt_action` | HITL 审批需要第三个 `ask_action` 实现：worker 线程阻塞等 GUI 对话框结果 | `gui_prompt_action(inv, *, permission_state, on_always_approve, …)`：GUI 对话框（审批卡片，对标 codex desktop 卡片）打开 → worker 阻塞 `threading.Event.wait()` → 对话框关闭 set 并取按钮选择 → 经 `decision_from_choice` 出 dict。契约与 modal/CLI 完全同构 |
| `gui_turn_gate.py` | `tui.py` L1026 `_turn_gate_threads`（thread 级门集合）+ L1274 `_release_turn_gate`（FIFO 重投）+ L1008 `_turn_workers` per-thread（后台回合）+ L1441/1478-1530 门判定分支 | TUI 的回合门/FIFO 排队绑在 `JarvisApp` 实例与 Textual Worker 生命周期上，GUI 需要等价串行化（否则同 thread 双 graph 并发 → SqliteSaver 锁竞争 + finalize_turn 交错，即 tui-ux7 修复的同一根因） | 纯 Python 实现：`set[thread_id]` 门 + 每 thread 消息 FIFO `deque`，门释放（presenter finally 等价点）经 GUI 主线程重投递。不碰 tui.py |
| `gui_main.py` | `main.py::main` 装配段 | 需要一个非 Textual 入口 | 装配段照抄：load_config → load_mcp_tools → `SqliteSaver.from_conn_string` → build_permission_interrupts → build_agent → JumpInRegistry → make_scheduler → `PySide6 app.run()`（框架定案 T-001：PySide6 + Nuitka） |

### Textual 专属、不迁移（划界，保持原样）

`tui.py`（JarvisApp / 三模态 PermissionModal-EditParamsModal-PrefixModal / @/补全 / 侧边栏 / spinner / 粘贴 IME）、`tui_turn.py`、`tui_log.py`、`tui_punct.py`、`ime_shim.py`、`input_probe.py`。GUI 的中文 IME 走 PySide6 原生（T-001 已实证达标），**不需要** ime_shim（ConPTY 专用）。

### 官方 seam 核查（红线项）

docs-langchain MCP（离线可读）确认：`stream_events` 事件契约（event-streaming 页）与 HITL interrupt/resume（interrupts / human-in-the-loop 页，`Command(resume=…)` 形状）即本项目 `run_agent_turn` 已落地的**官方契约本身**——本项目已经在 seam 上，**无需给 deepagents/langgraph 加任何新钩子/middleware**。外部先例：opencode 多客户端事件协议（serve 模式）、LangSmith `useStream` 多消费端——**离线推断、未验证**（web 检索不可达），仅作 B 方案形态参照，不编造链接；T-002/T-003 在线复核时验证。

## GUI 消费架构提案

**事件通道（不发明新协议）**：worker 线程 → GUI 全部走两条既有管道：
1. **流式**：`StreamCallbacks` 5 键（on_subagent / on_tool_call / on_message_delta / on_message_end / on_status）+ `run_agent_turn` 的 `on_stream_start` / `on_fallback_message` / `on_cancelled` / `on_turn_incomplete` 4 个参数。GUI presenter 实现回调时把富文本写操作 post 到 GUI 主线程。
2. **HITL**：`ask_action` 回调 + `{"decisions": [...]}` 回包。GUI 对话框是唯一的阻塞点。
取消 = `is_cancelled` + `RunControl.request_drain("user-cancel")`（tui-ux6 ADR-0008 语义照搬：当前步骤跑完即停）。

**进程/线程模型**：
- **A（MVP 推荐）GUI 进程内跑 graph**：主线程 = Qt 事件循环；每 thread 一个 worker 线程跑 `run_agent_turn`（与 TUI `@work(thread=True)` 同构）；回合门/FIFO 用 `gui_turn_gate`（纯 Python，无 Textual 依赖）。优点：与 TUI 行为逐项对齐（既有 202 单测语义直接覆盖 commands/streaming 层），MVP 零跨进程风险。
- **B（升级路径）独立 runtime worker 进程 + 事件通道**：GUI 瘦壳，graph 跑在 `python -m src.gui_runtime` 子进程，事件通道 = 现有 5 回调序列化为进程间消息（stdin/pipe JSON 行协议或本地 TCP），审批反向通道 = 子进程阻塞在 `ask_action` 时向父进程发 `{interrupts}` 请求、父进程回 `{"decisions": [...]}`。对标 opencode serve 形态（离线推断、未验证）。收益：GUI 崩溃不杀图执行、多窗口共享一个 runtime、SqliteSaver 单写者。**先 A 后 B**：A 的回调形状就是 B 的线协议，不推倒重来。

## 风险与未决

1. **SqliteSaver 锁竞争（TUI+GUI 并存时）**：两个进程共享 `checkpoint_db`（jarvis.json `checkpoint_db` 键）→ 并发写 checkpoint = `SQLITE_BUSY`（WAL 模式下读并行、写仍串行）。离线推断、未验证：`SqliteSaver.from_conn_string` 默认 busy_timeout 行为未实测。处置：MVP（A）若允许 TUI/GUI 同时开同一项目，需在 conn string 加 `?busy_timeout=…`/WAL pragma 并**同 thread 不同客户端串行**（回合门只保证本进程内串行）；B 方案天然单写者规避。
2. **`permission_state["thread_id"]` 互写**：共享 state 引用的 `thread_id` 键可被并发 sched-turn 覆写（AGENTS.md tui-ux12 已记录，fail-safe 方向）。同进程双客户端（A）会放大该窗口；跨进程（B）免疫（各进程独立 state）。加固 = 按 thread 分桶，**T-005 裁定后选项，不在本票动**。
3. **always_approve 写回 jarvis.json 的版本分叉窗口**：`commands.always_approve` 持久化 jarvis.json；GUI/TUI/`sched-*` 三写者同机时，后启动者启动快照 stale。MVP 单 GUI 主窗口可接受；B 方案 runtime 独占写 + 客户端只读。
4. **YOLO `state["yolo_threads"]` 纯进程内内存**：A 模式下 TUI/GUI 各自 app 实例 = 各自 state，互不感知（语义可接受：`/yolo` 只影响输入它的那条线程，本就设计成 app 内语义）；跨进程无共享，天然一致。
5. **JumpInRegistry / make_scheduler 不跨进程**：A 模式若 TUI+GUI 同开 = 双 scheduler 同 cron 重复执行 `sched-*` 回合。建议：后启动者检测到 runtime 已存在则不 start scheduler（或 B 方案单 runtime）。JumpIn 消息注入同理只在本进程生效。
6. **HITL 等待期的「取消」**：GUI 关闭审批对话框 = 回 None = 放弃本轮（与 modal 的 `q 放弃` 语义一致）；此时 drain 不生效（interrupt 在图外）。需在 GUI 对话框文案标注，避免用户以为 Esc/关窗是「取消执行」。
7. **stream_events v3 契约漂移**：TUI 与 GUI 共消费 `consume_stream_events`，langgraph 升级改事件形状时一处修全生效——这是「不发明新协议」的副作用红利，同时意味着 B 方案的线协议也要跟这个单一消费层。

## 来源

- 本仓（GUI worktree `src/` 副本）：`streaming.py`（全文）、`commands.py`（全符号表，L23 thread_config）、`tui.py`（L1008/L1026/L1258/L1274/L1441-1530/L1565/L1618-1646/L1745/L1922-1931/L2069-2087）、`tui_turn.py`（TurnPresenter L5-153，call_from_thread L48-151）、`permissions.py`（全符号表）、`agent.py::build_agent`（L280）、`jump_in_queue.py`（L21/L124）、`tui_format.py`（头注+import）。
- 主仓 AGENTS.md（历史语义：tui-ux6/7/11/12 条目，ADR-0008 drain 与 turn gate 根因 H1）。
- docs-langchain MCP（离线）：deepagents/langchain/langgraph 的 event-streaming / interrupts / human-in-the-loop / streaming 文档页存在且即本项目已用契约 → 无需新 seam。
- 外部先例：opencode serve 多客户端事件协议、LangSmith useStream —— **离线推断、未验证**（web 不可达，不附链接，T-002/T-003 在线复核）。
