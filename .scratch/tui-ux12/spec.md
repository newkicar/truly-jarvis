# TUI 体验十二（tui-ux12）：YOLO 模式（/yolo on|off）

**Type:** feature
**Status:** done
**Blocked by:** 无

## Problem Statement

审批体验优化（tui-ux8~10）落地后，HITL 审批（`execute/write_file/edit_file/delete` 默认 `ask`）
逐次确认在高信任场景（本机、可控任务）下成为操作摩擦：用户每步都要点 Modal。
需求（用户原话）：加入「YOLO 模式」开关——**所有动作均无须审批，agent 拥有最高权限**；
仅针对**本轮对话（当前 thread）**有效，**跨会话无效**；**需手动关闭**。命令：`/yolo on` 与 `/yolo off`。

grill 定案（不再追问，详见本 spec 的 Implementation Decisions）：

1. **权限边界**：YOLO 期间 bypass 4 个 gated 工具（`GATED_TOOLS`，src/permissions.py L25）的
   `ask` 中断与 `deny` 拦截；**vault 写保护是硬地板**（`VaultWriteGuardMiddleware`
   独立于 permission state，不动）。
2. **作用域（方案 b，线程级）**：`/yolo on` 只影响**输入它的 thread**。一个 app 运行 = 一个
   agent + 一份共享 `permission_state`（main.py 装配，`/sessions` 所有会话与 `sched-*` 定时
   线程共用该 dict——这也是 today「always approve」app 级的原因）。线程级语义：其余会话与
   定时任务保持原规则；每个会话在自己的内存里记住 on/off；**重启 app = 全部 off**。
3. **机制**：YOLO 永不改 `state["tools"]` 规则（无快照、无写回）——仅
   `state["yolo_threads"]: set[str]` 成员判定；`/yolo off` = 移除 thread_id，原规则原样。
4. **呈现**：模型侧**静默**（不注入 system prompt）；TUI 侧 Header sub_title 尾部
   `[YOLO]`（仅当前 thread 处于 yolo 时）+ on/off 各一条 notify；裸 `/yolo` = 只查询。
5. **不动**：`StepBudgetMiddleware`（步数预算提醒）与 `DoomLoopMiddleware`（5 次硬熔断）
   照常生效——YOLO 是审批特权，不是资源/熔断豁免；`PlanModeMiddleware` 正交（Plan 模式下
   写工具仍被 Plan 门拦截，即使 YOLO 开启）。
6. **文案**：幂等消息（重复 on →「已开启」）；`/yolo x` → `用法: /yolo on | /yolo off`；
   `_HELP_COMMANDS`/CLI_HELP/TUI_HELP 加一行；slash 补全加 `/yolo` 条目。

## Solution

四张线性工单：

1. **01 YOLO 内核（permissions 层）**：`build_permission_interrupts`（src/permissions.py L186，
   state 初始化 L205-212）state 增 `"yolo_threads": set()`；新增纯函数
   `yolo_on / yolo_off / yolo_active(state, thread_id)`；`_action_for_args`（L111）函数体**最顶部**
   插入一行短路 `if str(state.get("thread_id") or "") in state.get("yolo_threads", set()): return "allow"`
   （置于 hook 解析 L116 之前 = 最高权限语义，hook 也 bypass）。单 seam：`when` 谓词
   （L160 `_build_when`，ask 判定）与 `PermissionDenyMiddleware.block`（L281，deny 拦截）
   **都汇入 `_action_for_args`**——一处短路即同时消灭「审批弹窗」与「拒绝」；
   `interrupt_on` 在 agent.py 装配时只建一次、state 按引用共享 → **零 agent 重建、live 生效**。
2. **02 `/yolo` 命令端到端（CLI+TUI 共用）**：`commands.py` `dispatch_command`（L1082）新增
   `/yolo` 分支（on/off/裸查询/非法参数，幂等消息）；`_HELP_COMMANDS`（L30）加行；
   `src/slash_completion.py` 加 `SlashCommand("/yolo", "/yolo on | off", "YOLO 模式开关（仅当前会话）")`
   条目。验收：`/yolo on` 后本会话 gated 工具不再弹窗，`/yolo off` 恢复原规则。
3. **03 TUI 呈现层**：`src/tui.py` `_update_sub_title`（L1032，现有 项目+thread_id+MCP:N）
   尾部按当前 thread 的 yolo 状态加 `[YOLO]`（`/sessions` 切换时联动刷新）；on/off 时
   `app.notify` 一条（「YOLO 已开启：本会话所有动作免审批（vault 写保护与步数/熔断仍生效，/yolo off 关闭）」/「YOLO 已关闭」）。
4. **04 回归 + 文档 + 收官**：全量 pytest 对照基线（预存 test_config×3 已知失败除外）→
   AGENTS.md「TUI 体验十二」条目 → 四张工单勾选 + done → docs commit → push main。
   **注意**：push 触发的 CI 会撞上 THREAD A 的预存失败（CI 现解析 langchain 1.4.6，
   `tests/test_permissions.py::test_langchain_hitl_edit_decision_rewrites_tool_calls` 红）——
   与 YOLO 无关，单独修，不在本批阻塞项。

## User Stories

1. 作为用户，我对当前 app 运行完全放心时打 `/yolo on`，此后**本会话**所有 gated 动作
   （execute/write_file/edit_file/delete）直接执行、不再弹审批。
2. 作为用户，任务结束我打 `/yolo off`，本会话立即恢复原 `permissions` 规则（含 deny 拦截）。
3. 作为用户，裸 `/yolo` 告诉我当前会话是「开」还是「关」。
4. 作为用户，连打两次 `/yolo on` 得到幂等提示「已开启」（不是报错、不是「再次开启」歧义）。
5. 作为用户，我在会话 A 开 YOLO 后切到会话 B，B 的审批照常（线程级隔离）。
6. 作为用户，定时任务（`sched-*` 线程）不受我手动会话的 YOLO 影响，保持原规则。
7. 作为用户，重启 `python -m src.main` 后一切回到 off（无持久化，重启即全关）。
8. 作为用户，TUI 打开 YOLO 后 Header 看到 `[YOLO]` 标记，切回非 YOLO 会话标记消失。
9. 作为用户，开/关瞬间有一条 notify，不用去翻日志确认。
10. 作为用户，即便 YOLO 开着，写 `/vault/` 仍被 vault 写保护拒绝（地板不破）。
11. 作为用户，即便 YOLO 开着，步数预算提醒与 doom-loop 熔断照常（最高权限 ≠ 无限资源）。
12. 作为用户，Plan 模式下 YOLO 开着，写工具仍被 Plan 门拦（先规划），互不干扰。
13. 作为用户，`/help` 与 `/` 补全里能看到 `/yolo`（`/yol` 即出建议）。
14. 作为用户，`/yolo x` 得到 `用法: /yolo on | /yolo off` 提示。
15. 作为用户，开 YOLO 前已经弹出的审批弹窗**不**被追溯豁免——只有「之后」的调用免审批。
16. 作为用户，`--cli` 回退模式下 `/yolo` 与 TUI 行为一致。

## Implementation Decisions

- **线程级语义（方案 b）**：一份共享 `permission_state`（main.py 装配，所有 thread 共用），
  YOLO 状态 = `state["yolo_threads"]` 成员关系。`thread_id` 每轮由
  `sync_permission_context`（src/permissions.py L172，`streaming.run_agent_turn` 处调用）
  写入 state —— YOLO 短路读的就是它。
- **单 seam 短路**：`_action_for_args`（L111）顶部一行
  `if str(state.get("thread_id") or "") in state.get("yolo_threads", set()): return "allow"`。
  `when`（ask→interrupt）与 `PermissionDenyMiddleware.block`（deny→拦截）双路汇入，
  一处生效；短路置于 hook（L116-130）之前 = hook 也 bypass（「最高权限」语义定案）。
- **零重建**：`interrupt_on` 只在建 agent 时构造一次（state 按引用共享，live 语义
  tui-ux8「always approve」已实证）；YOLO 只动 `yolo_threads` 集合成员，**不改**
  `state["tools"]` 规则、**不写** jarvis.json、**不需要**快照/恢复路径。
- **helper 纯函数**：`yolo_on(state, thread_id)` / `yolo_off(state, thread_id)` /
  `yolo_active(state, thread_id)`（返回 bool，`thread_id` 空串 → False）——commands.py
  分发只调 helper，判定逻辑全部收在 permissions.py 便于单测。
- **模型侧静默**：不往 system prompt / wrap_model_call 注入任何 YOLO 说明；
  行为差异只体现在「工具不中断」。
- **TUI 呈现**：`_update_sub_title`（L1032）在 `MCP:N` 之后拼 `[YOLO]`；notify 文案见
  Solution-3；`/yolo` 命令本身经 dispatch_command 走，TUI/CLI 共用内核。
- **正交不动项**：vault guard、StepBudget、DoomLoop、PlanMode 均不读 `yolo_threads`，
  代码零改动（01 票以断言证明正交）。
- **自然推论（定案时已陈述，不重决）**：pending modal 不追溯豁免；`/replay`/`/fork`
  生成新 thread_id → 非 yolo（新会话需重新 on）；hooks 被 bypass。
- **并发已知边界（记录不解决）**：共享 `state["thread_id"]` 可能被并发 sched-turn 覆写
  （与现有 permission hooks 用法同源）：竞态方向一——用户 yolo 轮的工具调用读到 sched 的
  id（多弹一次窗，fail-safe）；方向二——sched 调用读到用户 yolo 的 id（窄窗口 bypass）。
  记录为 known limitation + 未来加固项（如 thread 内联传递），**不阻塞本批**。

## Testing Decisions

- 只测外部行为；四组锚点：
  1. `tests/test_permissions.py`：短路 ask→allow / deny→allow / off 恢复原规则 /
     线程 A yolo 线程 B 仍 ask（隔离）/ hook 被 bypass / `yolo_active` 纯函数组。
  2. `tests/test_vault_guard.py`（或 test_permissions 正交断言）：yolo 状态下 vault
     写拦截不变。
  3. `tests/test_commands.py`：`/yolo on|off`、裸查询、非法参数、幂等文案、help 行。
  4. `tests/test_slash_completion.py` / `tests/test_tui_completion.py`：`/yolo` 条目；
     `tests/test_tui.py`：Header `[YOLO]` 标记 + 会话切换联动 + notify（Textual pilot；
     modal 查询纪律不适用；**新测试禁 tmp_path/tempfile.mkdtemp**，自建目录）。
- 全量 pytest 对照预存失败基线（3× test_config 除外，`--ignore=tests/test_rag.py`）。

## Out of Scope

- 持久化（jarvis.json 不落盘 YOLO 开关；重启即 off 是特性不是缺陷）。
- vault 写保护 / 步数预算 / doom-loop 熔断 / Plan 门 —— 一律不动。
- 子线程（`/replay` fork、sched-*）的独立开关入口 —— 它们不在 yolo 集合里即安全默认。
- 模型对 YOLO 的感知（提示词注入）。
- THREAD A：CI langchain 1.4.6 HITL-edit 测试修复（预存失败，单独处理）。

## Further Notes

- AGENTS.md 条目在工单 04 收口（「TUI 体验十二」段，slug tui-ux12；注意 tui-ux11 已被
  AGENTS.md L42 HITL 编辑参数批次占用）。
- 命名沿用：`yolo_threads`（state key）、`[YOLO]`（Header 标记，全大写醒目）。
- 收官（2026-10-21）：四张工单 done；主 commit `1e7ff0c`；