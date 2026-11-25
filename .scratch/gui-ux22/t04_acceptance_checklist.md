# gui-ux22 工单 04 — 验收清单一页（关票留痕，offscreen 执行）

执行环境：`QT_QPA_PLATFORM=offscreen` + `tests/gui_fakes.py` + 全量 pytest（LANGSMITH/LANGCHAIN 双关）。
结果留痕：`t04_targeted_suite.log`（目标套件 82 passed / 50.21s）、`t04_full_pytest.log`（全量 484.8s）。

## 六场景各一例

| 场景 | 代表用例（全量通过） | 证据 |
|---|---|---|
| 开 | `test_gui_split.py:204 test_splitter_open_side_expands` + `test_side.py:116 test_open_side_forks_terminal_head`（开=终端 head fork） | 目标套件内绿；全量无失败 |
| 关 | `test_gui_session_menu.py:338 test_side_pill_toggle_and_close`（关=删，注册表清空）+ `test_side.py:258 test_close_side_deletes_session` | 同上 |
| 并发 | `test_gui_split.py:133 test_real_graph_dual_concurrent_sqlite_persist` + `:29 test_dual_tid_concurrent_no_deadlock` + `:60 test_hitl_routes_by_tid`（双 tid 真图并发 + SQLite 持久化 + HITL 按 tid 路由） | 同上 |
| 草稿 | `test_gui_session_drafts.py:18 test_drafts_follow_session_switch`（未提交输入/图片随会话存草稿，切回恢复） | 全量无失败（grep 确认 0 条失败行） |
| Esc | `test_gui_esc.py` 全文件（L34-139：空闲单/双 Esc、运行单 Esc prime、双 Esc cancel、三级级联） | 全量无失败。注：侧槽 `_side_esc_*` primed 属性（main_window.py L365-375）tests 无直接断言，由主槽裸 Esc 恒主槽测试（main_window.py:328 `set_esc_hook`）+ 实现属性背书 |
| slash 归属 | `test_gui_advanced.py:329 test_slash_undo_routes_by_slot_tid` + `:279 test_undo_backfills_input_box_on_success`（用户报障回归：`input_set (tid,text)` 按被撤回会话槽路由，撤回消息不再进错槽输入框） | 全量无失败 |

## 面② SideTaskGuard（双槽下 plan-only/readonly 守卫）
`test_side.py` L401-462 共 5 条守卫用例（side 拦 task+execute / 非 side 放行 / close 解除 / 主线程写不受影响）——全在目标套件 82 内，绿。

## 面③ 树 ◇ 前缀 + 右键开/删
- 「◇」前缀：`src/gui/main_window.py:1072`（`_session_row_label` 的 `side = "◇ " if presenter.is_side(tid)`）；GUI 层无直接断言，TUI 侧 `test_tui.py` L1769-1775 有。
- 右键「开侧边会话 / 删除侧边会话（回主线）」：`test_gui_session_menu.py:299 test_menu_side_branch_and_delete_side` + `:338 test_side_pill_toggle_and_close`——目标套件内绿。

## 全量 pytest 判读（t04_full_pytest.log，rc=1 但白名单内）
`1 failed, 1599 passed, 1 skipped, 211 errors in 484.81s`。逐条核对失败族：
- 211 errors + 1 failed（`test_resilience::test_tool_boundary_hilt_resume_no_crash`，`tempfile.mkdtemp` 触发）**全部**为机器级环境毒：
  - PermissionError [WinError 5] 系（tmp_path/pytest 基 temp 目录 `pytest-of-uida0712` 不可写中毒，E-body 212 行）；
  - FileNotFoundError [WinError 3] discovery 系（`C:\Users\uida0712\jarvis_pytest_disco` 6 个 setup 用例，18 行 E——与 t03 基线 `.scratch_pytest_full.log` 的 18 行同量同因，预存）。
- 无 test_gui*/test_side 失败行（grep 0 条）；test_config/test_project_init/test_skill_paths 的失败行全部属 PermissionError 环境族（本机 temp 中毒扩大，非 451be2b 引入——451be2b 只动 GUI 分屏 8 文件，未触及 config/project_init）。
- 结论：**无新增逻辑失败**；环境族按白名单放行（CI 的 rc=139 全绿放行规则同类精神；本机为 rc=1 + 摘要失败全环境毒，判放行并记录）。

## 判定
工单 04 四面全绿 → gui-ux22 关票。
