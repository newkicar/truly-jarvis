# 01 — Esc 取消 banner（spinner 即时可见「已取消，正在收尾」）

**What to build:** Esc 取消（worker 活跃分支）后，`#status_spinner` 在 drain 收尾期间仍转 `spinner_line` 帧（含 `SPINNER_TEXT="思考中..."`），用户无法分辨「还在思考」与「在取消收尾」。新增 `JarvisApp._show_cancel_banner()`：

- 停 `self._spinner_timer`（复用 `_hide_spinner`（src/tui.py L1044-1047）的 None-guard 停止模式：`stop()` + 置 None）。
- `spinner = self.query_one("#status_spinner", Static)`；`spinner.add_class("-active")`；`spinner.update("[dim]已取消，正在收尾（当前步骤结束后停止）[/dim]")`。
- 配置 `spinner_style == "none"`（`_spinner_config()` L1013 返回 `(animations, style)`）时 `_show_spinner` 是 no-op，banner 同步 no-op（优雅降级，不崩）。
- 调用点：`action_cancel`（L1645）worker 活跃分支、`worker.cancel()` **之前**调 `self._show_cancel_banner()`；**保留**既有 `log.write("[i][dim]（已取消）[/dim][/i]")`（既有测试 `test_escape_cancels_streaming` 断言 `已取消 in joined` 依赖它）。
- `TurnPresenter` 零改动：收尾结束（drain 完成）时其 finally 的 `_hide_spinner`（`src/tui_turn.py` L206）自动清空 banner；presenter 侧 `write_line` 在 cancelled 时抑制（tui_turn L59-61）已去重，日志「已取消」恰一条。
- 红灯测试（`tests/test_tui.py` 追加，仿 `test_escape_cancels_streaming` 的 SlowAgent）：发「慢请求」→ sleep 0.1 → `app.action_cancel()` → 断言 `str(spinner.renderable)` **无「思考中」且 有「已取消」**；sleep 0.5 后断言 banner 已清空；`joined.count("已取消") == 1`（日志恰好一条）。修复前 spinner 是 `spinner_line` 帧（含「思考中」）→ RED。

**Type:** bug
**Status:** done (2026-10-18, commit 4ae094f)
**Blocked by:** 无

## 验收
- [x] banner 红灯测试绿（取消后 spinner 无「思考中」、有「已取消」；收尾结束后清空）
- [x] 既有 TUI 测试无回归（`test_escape_cancels_streaming` 的 `已取消 in joined` 保持成立，恰一条）
- [x] `spinner_style="none"` 时 banner no-op 不崩

## Comments
2026-10-18 实施（commit 4ae094f）：
- 改动：`src/tui.py` 新增 `JarvisApp._show_cancel_banner`（停 `_spinner_timer` + `#status_spinner` 固定 dim 文案「已取消，正在收尾（当前步骤结束后停止）」；`spinner_style=none` 时 no-op；收尾结束由 presenter finally 的 `_hide_spinner` 自动清空，presenter 零改动）；`action_cancel` worker 活跃分支在 `worker.cancel()` 之前调用；`tests/test_tui.py` 追加 2 条 banner 红灯测试。
- 结果：banner 测试 2/2 绿；`test_escape_cancels_streaming`「已取消」恰一条保持成立，无回归。

diagnosing-bugs 六阶段痕迹（本批共享）：
- Ph1 假设：H0 spinner 未 stop 致「思考中」残留；H1 无守护 run_worker → 同 thread 双 graph 并发（慢响应直接原因）；H2 SqliteSaver 锁竞争；H3 模型限流退避（次级放大）。
- Ph2 RED：banner 测试见 spinner `⠸ 思考中...`；gate 测试首断言 `agent._calls == 2` / `max_overlap == 2`（修复前并发 = 2）。
- Ph3 根因确认 = H1（同 thread 双 graph 并发 → SqliteSaver 锁竞争 + finalize_turn 交错）。
- Ph4 GREEN：3 gate + 2 banner 测试全绿。
- Ph5 回归：5 文件组合（test_tui / test_tui_turn_gate / test_tui_turn / test_tui_spinner / test_streaming）65 绿 × 8 轮 0 失败；全量 557 绿 + 4 预存/flaky 失败（3× test_config 预存 + 1× test_streaming drain 慢工具 flaky，与本批 NoMatches 防御同根因，单跑 2/2 通过）无新增。
- Ph6 教训：回合级资源（worker / graph / checkpoint 写）必须 thread 级串行化门守护；drain 语义下「取消 ≠ 线程立即死亡」，UI 呈现（banner）与逻辑（门）需配套；worker 线程 UI 写必须对节点生命周期容错（NoMatches，Textual 8.x 在 `textual.css.query`），否则 drain/FIFO 时序下间歇 WorkerFailed；测试时序用轮询可观测状态，不用固定 sleep 对齐窗口。

