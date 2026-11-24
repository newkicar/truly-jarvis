# ADR-0013: goal 持久化与自动续跑——goals.json 单进程存储 + 回合门 FIFO 续跑链

**状态:** 已接受（2026-11-24）

## 背景

跨回合长任务（「重构到全绿」、「一次实现 N 个功能」）此前无目标追踪、无自动续跑、无预算：
用户每轮手动「继续」，Esc 中断即丢进度，模型没有「还差多少」的概念。对标 codex `/goal`
（codex-rs `goals/continuation.md` + `goals/budget_limit.md` 提示词模板）：持久目标 +
自动续跑回合 + 续跑预算 + 四态状态机 + 完成审计 + 零工具调用防转圈。

硬约束来自既有架构纪律：CLI/TUI/GUI 三前端共用纯逻辑层（`commands.py` 同款「纯函数 +
state 注入」纪律）；会话级 UI 写路径须走 tui-ux7 回合门 FIFO / GUI TurnGate（不新增排队机制）；
goal 状态与 HITL 审批、Plan/Act 模式、YOLO、vault 写保护、韧性中间件全部正交（零改 + 回归断言）。

## 决策

1. **存储 = `~/.jarvis/goals.json` 单进程单文件**（`JARVIS_HOME` 可覆盖），顶层 dict 按
   `thread_id` 键；原子写 = 同目录 `goals.json.tmp` + `replace`（Windows 原子 rename 语义）；
   缺文件 / 损坏 / 非 dict → warning + 空 dict（不崩）。记录 shape：
   `{thread_id, goal_id, objective, status, turns_used, max_turns, completed_at?, audit_evidence?}`。
   `goal_clear` 留 **int 墓碑**（被删记录的 goal_id）保持后续 set 的 goal_id +1 序列不断；
   乐观版本 `expected_goal_id` 参数存储层透明支持（命令层不传，测试注入）。
2. **四态状态机** active / paused / **budget_limited / complete（终态）**；终态重设须
   `/goal clear`。一会话一个在途目标（`goal_set` 遇 active/paused → `GoalExistsError`）。
   `complete` 唯一写路径 = `goal_complete(audit_evidence)`（证据 strip 后为空 →
   `EvidenceRequiredError`，「无证据不得标记完成」）。
3. **续跑触发真值表（全满足才续）**，纯函数 `should_continue(goal, turn, ctx)` /
   `continuation_decision(...)`（src/goals.py，turn 鸭子类型 `.outcome/.tool_calls_count`，
   不 import streaming）：status=active && turns_used<max_turns && outcome∉(cancel,abandon)
   && tool_calls_count>0 && 非 Plan 模式 && 无悬挂 HITL interrupt && 非 `sched-*` 线程。
   **零工具调用回合 = 断链**（防模型空转「只说不做」自激循环，对标 codex 无工具调用抑制）。
   **Esc 取消 = 断链非暂停**：该回合不续跑，goal 保持 active，用户可 resume 或自然重设。
4. **三前端续跑接线（票 05/06）**，统一走既有回合门 FIFO，不新造排队机制：
   - GUI（`src/gui/runtime.py` turn finally）：`continuation_decision` → kind∈(continuation,
     budget) 且窗口未关 → `goal_note_turn` + `gate.try_start(tid, decision.prompt)`
     （tid 仍在 `_running` → 返回 queued，`finish_full` 弹头重投，零新机制）；
     用户输入以「[目标预算耗尽」开头 → 收尾轮跑完后 `goal_mark_budget_exhausted`（**后置终态**）。
   - TUI（`src/tui_turn.py` presenter finally）：同款判定 + dim 系统行渲染（`goal_input_label`
     纯函数 → 「目标续跑 n/m」「目标收尾 n/m」，三前端共用）+ 入回合门 FIFO。
   - CLI（`src/main.py` `_cli_goal_step` 纯判定）：`_stream_turn` while 循环替换
     user_input 直接续跑；**`_stream_replay` 不续**（replay = 历史回放，非活会话）。
   - **budget_limited 后置**：预算收尾轮（携 budget_prompt）跑完才 mark 终态；过早 mark 会让
     收尾轮内 `complete_goal` 抛 TerminalGoalError；CLI 的 mark 判定独立于 kind 门（预算轮
     decision 必为 none，放 kind 门后不可达）。
5. **模型侧仅 3 工具**（`src/goal_tools.py`，`agent.py` 构建时注入，MCP 同款注入位）：
   `create_goal(objective, max_turns?)` / `complete_goal(audit_evidence)` / `get_goal`。
   **仅主代理**注入；researcher / knowledge_keeper / `jarvis.json` 自定义子代理均不含。
   不给模型 pause/resume 工具（**人类命令面** `/goal pause|resume`）。工具层边界：异常族
   （GoalError 全族）一律转 str 文本返回，不 raise；thread_id 调用时从 permission_state
   共享引用读（streaming 每轮开头写入）。
6. **预算 = 回合数（MVP）**：`DEFAULT_GOAL_MAX_TURNS=5`，`jarvis.json` `goals.max_turns`
   覆盖（钳 [1,9999]，非整数回落默认）；对新设 goal 生效。token 预算（usage_metadata
   累计）为二期，Out of Scope。
7. **提示词移植纪律**（codex continuation.md / budget_limit.md 字面纪律）：续跑轮逐条审计
   目标 → 有缺口继续（「微调参数≠换方案」「harness 拦截的命令不许重发」）→ 全达成必须
   调 complete_goal 附证据；预算轮 = 收尾交接轮（禁开新工作，产出「已完成/未完成/下一步」
   结构化交接）。
8. **正交性（零改 + 回归断言）**：YOLO 短路先于续跑判定（YOLO 线程免审批不豁免审批弹窗的
   语义不变）；HITL 审批照常不豁免（续跑轮仍走 permissions）；Plan 门先于续跑（Plan 时
   decision=none）；VaultWriteGuard 写保护地板、StepBudget/DoomLoop/NoProgress 韧性中间件
   全正交；`/undo`、`/compact` 为消息层操作，不触 goal 状态。

## 后果

- 展示面：TUI header sub_title `[GOAL] n/m status`（仅 active/paused，/sessions 切换联动）+
  续跑输入 dim 系统行；GUI 状态栏目标状态行；CLI headless 目标状态行。`/goal` 命令三前端
  共用 dispatch（status/pause/resume/clear 四态幂等文案，跨重启持久）。
- 已知并发边界（记录不解决，与 tui-ux12 YOLO 已知项同源）：goals.json 单进程写，共享
  `permission_state["thread_id"]` 可被并发 sched-turn 覆写；竞态方向 fail-safe（最坏 = 该
  轮不续跑或写偏线程，不损坏文件），多人多进程场景二期再做进程锁。
- 测试面：goal 专项 5 文件 67 测（test_goals / test_goal_tools / test_cli_goal /
  test_gui_goal / test_tui_goal），正交回归 test_permissions / test_vault_guard /
  test_resilience / test_plan_mode 零改全绿。

## 考虑过但拒绝的选项

- **sqlite 存 goals**：checkpoint db 属 SqliteSaver 职责；goal 是高频小写、机器管理、
  用户不手工编辑的 dict 状态，单文件 JSON 原子写够用且零新依赖（schedules 式「每任务一
  文件」否——高频小写下每线程一文件碎片化且无人类编辑诉求）。
- **模型侧给 pause/resume 工具**：暂停/恢复是用户意图边界（人类命令面），模型自决暂停
  与「complete 必须附审计证据」的审计纪律冲突。
- **预算耗尽立即 mark budget_limited（收尾轮前）**：收尾轮内模型仍可 complete_goal 附
  证据（目标其实已完成的情况），提前翻终态会令其抛 TerminalGoalError；故后置到收尾轮
  跑完才 mark（各前端在收尾输入被消费时判定）。
