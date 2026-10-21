# 04 — 收官：全量回归 + AGENTS.md + 工单勾验 + push

**What to build:** 批次收口（对照 tui-ux10 的 04 号工单同构）：

- 全量 `pytest`（`--ignore=tests/test_rag.py`）对照**预存失败基线**
  （3× test_config 已知坏；本批新增必须 0 失败 0 新错）；锚点族全绿
  （test_permissions / test_vault_guard / test_commands / test_tui / test_tui_modals /
  test_slash_completion / test_tui_completion）。
- AGENTS.md 加「**TUI 体验十二**（`tui-ux12`，<日期>，YOLO 模式）」条目，密文风格对齐
  tui-ux10 段：线程级语义（方案 b 定案 + Q2 追问背景）、`yolo_threads` + `_action_for_args`
  L111 单 seam 短路（ask/deny/hook 三 bypass、零 agent 重建）、模型侧静默、Header `[YOLO]`、
  幂等文案、正交不动项（vault/预算/熔断/Plan）、并发已知边界（共享 thread_id 覆写竞态，
  fail-safe 方向记录）、自然推论（pending modal 不追溯、replay/fork 新 thread 非 yolo）；
  附 commit 号。
- 四张工单文件 `Status:` 改 done + commit 号，验收项逐条勾选。
- commit（中文 conventional：`feat(tui-ux12): YOLO 模式 /yolo on|off（线程级免审批）`）+ push main。
- **CI 已知风险（不阻塞本票）**：push 触发 CI 会撞 THREAD A 预存失败（langchain 1.4.6
  下 `test_langchain_hitl_edit_decision_rewrites_tool_calls` 红，与 YOLO 无关）；
  若 push 后 CI 红即此单一原因，向用户报备，THREAD A 单独起票修复。

**Type:** chore
**Status:** done
**Blocked by:** 01, 02, 03

## 验收
- [x] 全量 pytest 对照基线无新增失败
- [x] AGENTS.md「TUI 体验十二」条目落盘（含并发边界与自然推论记录）
- [x] 四张工单 done + 勾选；spec.md Status 改 done
- [ ] commit + push main；CI 状态检查（仅允许 THREAD A 预存红，且已向用户报备）（CI 绿后补勾）

**Done:** 2026-10-21，主 commit `1e7ff0c`。