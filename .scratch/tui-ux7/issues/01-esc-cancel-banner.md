# 01 — Esc 取消 banner（spinner 即时可见「已取消，正在收尾」）

**What to build:** Esc 取消（worker 活跃分支）后，`#status_spinner` 在 drain 收尾期间仍转 `spinner_line` 帧（含 `SPINNER_TEXT="思考中..."`），用户无法分辨「还在思考」与「在取消收尾」。新增 `JarvisApp._show_cancel_banner()`：

- 停 `self._spinner_timer`（复用 `_hide_spinner`（src/tui.py L1044-1047）的 None-guard 停止模式：`stop()` + 置 None）。
- `spinner = self.query_one("#status_spinner", Static)`；`spinner.add_class("-active")`；`spinner.update("[dim]已取消，正在收尾（当前步骤结束后停止）[/dim]")`。
- 配置 `spinner_style == "none"`（`_spinner_config()` L1013 返回 `(animations, style)`）时 `_show_spinner` 是 no-op，banner 同步 no-op（优雅降级，不崩）。
- 调用点：`action_cancel`（L1645）worker 活跃分支、`worker.cancel()` **之前**调 `self._show_cancel_banner()`；**保留**既有 `log.write("[i][dim]（已取消）[/dim][/i]")`（既有测试 `test_escape_cancels_streaming` 断言 `已取消 in joined` 依赖它）。
- `TurnPresenter` 零改动：收尾结束（drain 完成）时其 finally 的 `_hide_spinner`（`src/tui_turn.py` L206）自动清空 banner；presenter 侧 `write_line` 在 cancelled 时抑制（tui_turn L59-61）已去重，日志「已取消」恰一条。
- 红灯测试（`tests/test_tui.py` 追加，仿 `test_escape_cancels_streaming` 的 SlowAgent）：发「慢请求」→ sleep 0.1 → `app.action_cancel()` → 断言 `str(spinner.renderable)` **无「思考中」且 有「已取消」**；sleep 0.5 后断言 banner 已清空；`joined.count("已取消") == 1`（日志恰好一条）。修复前 spinner 是 `spinner_line` 帧（含「思考中」）→ RED。

**Type:** bug
**Status:** ready-for-agent
**Blocked by:** 无

## 验收
- [ ] banner 红灯测试绿（取消后 spinner 无「思考中」、有「已取消」；收尾结束后清空）
- [ ] 既有 TUI 测试无回归（`test_escape_cancels_streaming` 的 `已取消 in joined` 保持成立，恰一条）
- [ ] `spinner_style="none"` 时 banner no-op 不崩

## Comments
