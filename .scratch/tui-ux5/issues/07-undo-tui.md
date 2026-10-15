# 07 — TUI /undo + 双 Esc + transcript 重建 + 空闲 Esc 不退

**What to build:** `_handle_user_message` 特判 startswith("/undo") → worker 跑 commands.undo → call_from_thread 重建 transcript（log.clear() + log.write(render_session_text(agent, tid)) + 结果横幅）；`JarvisApp._esc_primed_at`：action_cancel 中 worker 活跃 → 现有取消语义不变；空闲 → now-last≤1.5s 触发 /undo 1（含 _bump / _mark_hitl_resolved 舞蹈），否则 notify「1.5s 内再按 Esc 撤回上一轮」+ 记时；空闲单 Esc 不再走 Textual 默认退出（退出保持 ctrl+q / ctrl+c）。

**Type:** task
**Status:** done
**Blocked by:** 06

## 验收
- [ ] 单测：空闲双 Esc（1.5s 内）→ /undo 1；间隔 >1.5s → 仅 notify；worker 活跃 Esc → 取消（不回归）
- [ ] 空闲单 Esc 不再退出 app（action_cancel 短路默认行为）
- [ ] /undo 走与 /replay 同级的 worker 特判路径；transcript 重建后对话区显示正确
- [ ] 帮助文案（_HELP_COMMANDS / TUI_HELP）补 /undo 与双 Esc 说明

## Comments