# JARVIS goal：/goal 持久目标 + 自动续跑（对标 codex /goal）

**日期：** 2026-11-24  
**状态：** done（2026-11-24，工单 01–07 全部关闭；ADR-0013 + AGENTS.md goal 决策一笔 + 全量回归零新增失败）  
**动机：** 跨回合长任务（"重构到全绿"、"一次实现 N 个功能"）现无目标追踪、无自动续跑、无预算；用户每轮手动"继续"，中断即丢进度，模型没有"还差多少"的概念。对标 codex /goal（持久目标 + 自动续跑回合 + 续跑预算 + 四态状态机 + 完成审计 + 零工具调用防转圈）。jarvis 当前零 `goal` 相关代码（src/、docs/ 全量 grep 零命中）。

---

## Problem

| # | 痛点 | 现状 | 解决方向 |
|---|------|------|----------|
| A | 长任务要手动推进 | 每轮结束等用户说"继续" | 自动续跑回合（continuation）+ 续跑预算 |
| B | 无目标状态，中断丢进度 | 无持久化层 | `~/.jarvis/goals.json` 按 thread_id 持久化 |
| C | 模型"只说不做"空转 | 步数预算只是全局上限 | 零工具调用回合抑制 + complete 必须附审计证据 |

## Solution

- `/goal <objective>`（或模型 `create_goal`）声明目标；每个回合结束后系统自动排队"续跑回合"（输入 = continuation prompt），直到：
  - 模型 `complete_goal(audit_evidence)` 审计通过（objective 逐条达成、必须附证据），或
  - 续跑预算耗尽（默认 5 回合，`jarvis.json` `goals.max_turns` 可覆盖）→ 终态 `budget_limited`，最后一轮为收尾交接轮（budget prompt）。
- 命令面：`/goal <objective>|status|pause|resume|clear`；Esc 取消 = 断链（该回合不续跑，goal 保持 active，非暂停）；Plan 模式不续跑；HITL 审批照常（goal 不豁免任何审批）。
- 模型侧仅主代理注入 3 工具：`create_goal` / `complete_goal` / `get_goal`（不给 pause/resume——人类命令面）。
- 一会话（thread）一个 active goal；sched-* 线程不参与续跑；side-* 线程独立 goal 空间。

## User Stories

1. 用户 `/goal 重构 settings 模块，直到 202 个单测全绿`；回合结束后系统自动排队续跑，无需手动"继续"。
2. 续跑回合状态行显示「目标续跑 N/M」，用户可见进度。
3. `/goal status` 查看目标 objective、状态与续跑进度。
4. 审批中或 Plan 模式时不续跑；回到 Act 恢复。
5. Esc 取消当前回合 → 该回合不续跑，goal 保持 active。
6. 模型完成判断后调 `complete_goal` 附审计证据 → 终态 `complete`，续跑链断开。
7. 已有未完成 goal 时再 `/goal <new>` → 提示失败（一会话一目标）。
8. `/goal pause` / `/goal resume` 暂停/恢复，objective 不变。
9. `/goal clear` 删目标，回到一次性对话。
10. 续跑预算耗尽：自动触发预算收尾轮（「已完成/未完成/下一步」结构化交接）→ 终态 `budget_limited`，需 clear 后重设。
11. 模型某回合零工具调用 → 不触发下一次续跑（防转圈）。
12. 重启 app 后 goals.json 状态仍在，active goal 可继续续跑。
13. sched-* 定时任务线程不参与 goal 续跑。
14. side-* 侧线程独立 goal 空间，互不影响。
15. `/undo`、`/compact` 不改变 goal 状态（消息层操作正交）。
16. TUI header sub_title 在有 active goal 时显示 `[GOAL]` 标记，无则不显。
17. GUI 状态栏显示 goal 状态；CLI headless 显示 goal 状态行。
18. 模型经 `get_goal` 读当前目标/剩余预算/状态，不盲猜。
19. `create_goal` 在已有未完成 goal 时返回失败提示。
20. `complete_goal` 无审计证据时失败，须补证据。
21. 模型主动调 `create_goal` 时 TUI notify 告知用户已设目标。
22. 编辑 `jarvis.json` `goals.max_turns` 调整续跑预算（对新设 goal 生效）。

## Implementation Decisions

### 模块与存储

- 新 `src/goals.py`（纯逻辑，CLI+TUI+GUI 共用，`commands.py` 同款纪律：纯函数 + state 注入，可单测）。
- 存储 = `~/.jarvis/goals.json`（`JARVIS_HOME` 可覆盖），顶层 dict 按 thread_id 键；原子写 tmp+rename；机器管理单文件 dict（否掉 schedules 式"每线程一文件"——goal 高频小写、用户不手工编辑；不用 sqlite，checkpoint db 属 SqliteSaver 职责）。
- 记录 shape：`{thread_id, goal_id(int, set 时+1, 乐观版本), objective, status: active|paused|budget_limited|complete, turns_used, max_turns(默认 5, goals.max_turns 覆盖), completed_at?, audit_evidence?}`。
- 单进程写；并发限制与 YOLO 共享 state 竞态同源（ADR 记录为已知项，不解决）。

### 状态机

- 四态 active / paused / budget_limited / complete；complete 与 budget_limited 为终态，重设须 clear。
- goal_id 每次 goal_set +1；同线程并发写乐观版本检查，stale 写显式失败。

### 模型工具（仅主代理，启动时一次性注入，MCP 同款注入位；子代理不含）

- `create_goal(objective, max_turns?)`：已有未完成 goal → 失败（一会话一目标）。
- `complete_goal(audit_evidence)`：唯一 complete 写路径；必须附审计证据。
- `get_goal`：返回 objective / status / turns_used / max_turns / 剩余。
- 不给 pause/resume 工具（人类命令面）。

### 命令（三前端共享 dispatch）

- `/goal <objective>|status|pause|resume|clear`；单 dispatch 函数，yolo_command_text 写法四态幂等文案；`slash_completion.py` 条目。

### 续跑触发（回合收尾钩子，三前端共用）

- 回合 finalize 后调纯函数 `should_continue(goal, turn_outcome, ctx)`。
- 触发条件（全部满足）：status=active && turns_used < max_turns && 本回合 tool_calls > 0 && 非 Plan 模式 && 无悬挂 interrupt && 非 sched-* 线程。
- 触发后续跑输入（continuation_prompt，与 /compact 延续摘要同形状）排队走 tui-ux7 回合门 + FIFO（TUI）；GUI per-tid gate + UiBridge；CLI headless 直接续跑。
- turn_outcome=cancel（Esc drain）→ 该回合不续跑，goal 保持 active（断链非暂停）；abandon → 不续跑。

### 防转圈

- 零工具调用回合不触发下一次续跑（对标 codex 的无工具调用抑制）。

### 预算耗尽

- 最后一续跑轮携 budget_prompt（禁开新工作、收尾交接话术）→ 后置 `budget_limited`（终态，需 clear 重设）。

### 提示词

- continuation_prompt 移植 codex `goals/continuation.md` 纪律：逐条完成审计 → 有缺口继续 / 全达成必须调 complete_goal 附证据；「微调参数≠换方案」；「harness 拦截的命令不许重发」。
- budget_prompt 移植 codex `goals/budget_limit.md`（收尾交接、禁开新工作）。

### Prefactor

- `run_agent_turn` 返回 `TurnOutcome(ok, outcome, tool_calls_count, last_usage)` dataclass；`.ok` 保 legacy bool 语义；5 调用点迁移（main.py ×2、tui_turn.py ×1、gui/runtime.py ×2，行号以当前 HEAD 为准）。

### 正交性（零改 + 回归断言）

- VaultWriteGuard / StepBudgetMiddleware / DoomLoopMiddleware / NoProgressGuardMiddleware / PlanModeMiddleware / permissions+YOLO 均与 goal 正交；Plan 门先于续跑（Plan 时不续跑）。

### 展示

- TUI header sub_title `[GOAL]` 标记（/sessions 切换联动刷新）+ 续跑回合状态行「目标续跑 N/M」；GUI 状态栏等价；CLI headless goal 状态行。

### 文档

- 新 ADR（当前 ADR 最大号 +1，暂编号 0013）+ AGENTS.md 关键决策一笔 + .scratch 关票。

## Testing Decisions

- 最高 seam 测试层 = goals 纯函数（tests/test_goals.py）：状态机全迁移 / goal_id 版本冲突 / `should_continue` 真值表（active、paused、预算耗尽、complete、零工具调用、Plan、sched-*）/ prompt 渲染 / goals.json 原子写（自建目录纪律，禁 tmp_path）。
- 命令契约：test_commands 增 `/goal` 五子命令 × 四态幂等文案 + 跨重启持久（重开 goals.json 重载）。
- 工具注入契约：主代理含 3 工具 / 四类子代理 spec 不含（sanitize 子代理断言同款）；create 重复失败；complete 无证据失败。
- 续跑触发：monkeypatch streaming / 回合收尾钩子 + offscreen harness（gui_fakes / TUI 测试先例 tui-ux12/14）；Esc 取消 → 不续；预算耗尽 → budget_limited + 收尾轮；complete → 断链。
- 正交回归：test_permissions / test_vault_guard / test_resilience / test_plan_mode 零改全绿。
- 全量回归零新增失败（排除预存 test_config×3 红）。

## Out of Scope

- token 预算（MVP 用回合数；二期 usage_metadata 累计）。
- 模型侧 pause/resume 工具。
- sched-* 定时任务设目标。
- 跨进程 goal 同步（单进程假设）。
- `/goal edit`（改 objective = clear + 重设）。
- 自动建议 goal。
- /undo、/compact 与 goal 交互特判（消息层不动 goal 状态）。

## Further Notes

- 对标素材 = codex-rs commit `6014b66` 的 `goals/continuation.md` + `goals/budget_limit.md` 提示词模板，OpenAI cookbook "Using Goals in Codex"（社区逆向 gist，仅参考）。
- 工单：`issues/` 01–07（一文件一工单，依赖序；01/02 可并行起步，关键路径 01→04→05→06→07，03 与 04 并行）。
