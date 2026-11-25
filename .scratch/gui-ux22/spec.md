# gui-ux22: GUI 侧边会话分屏（左主线 / 右侧边，QSplitter 双槽）

## 问题陈述（2026-11-24）
侧边会话内核已完成、本次**零改动**：`commands.open_side`（fork 主线 head → 新 thread
`side-<uuid8>`，每条主线至多一个，side-exists 门控）/ `commands.close_side`（= `delete_session`，
删除分叉、回主线）；侧边会话 = plan-only/readonly（`permissions` side state +
`SideTaskGuardMiddleware`，execute + task 禁用）。
GUI 现状是整屏切换（`main_window._switch_to` 换 stack 页）：开侧边即看不见主线上下文，
无法一边盯主线任务进度、一边续侧边任务。Codex `/side` 语义已验证 = 临时 fork
（河水分叉，两边可同时编辑，关闭 = 删除分支、主线留在主线程），jarvis 内核语义完全一致；
本工作 = **纯表现层**，kernel / streaming / permissions 零改动。

## 方案
中央区 QSplitter 水平分屏：左槽 = 主线（现有单列组件归位），右槽 = 侧边会话（同形
StatusView / QueueStrip / ImageStrip / InputBar 四件套 + ChatPane）。右槽默认折叠（不可见），
开侧边会话时（slash 或树右键「开侧边会话」）展开；**关 = `close_side` 删除语义**
（分叉被删、焦点回主线、右槽折叠），不是普通切走。主线任务进行中时允许两 graph
并发流式（TurnGate 已 per-tid）。

## 实现决策
1. **布局**（`main_window.py` L236-261）：现有中央列包进 `QSplitter(Qt.Horizontal)`；
   - 左槽 = 现有单列四件套（L242-261），ChatPane re-parent 不变（仍 per-thread 常驻 +
     sticky-bottom + 150ms flush_dirty）；
   - 右槽 = 四件套各独立实例（不再共享 L245-260 的单例），ChatPane 仍取自 `panes` dict、
     只在槽间 re-parent；
   - 右槽初始隐藏（collapsible）；QSplitter 原生拖动调比例在范围内（零实现）；跨重启的 splitter 比例持久化 out of scope。
2. **槽位焦点与键位路由**：每槽 InputBar 独立输入草稿、tab hook、esc hook、cancel 按钮；
   - CompletionPopup 每槽一个（L272-287 的绑定逻辑复制），仅焦点槽的 popup 活跃；
   - Esc 三级状态机（L289-296，`ESC_UNDO_WINDOW=1.5`）升为槽级：每槽独立
     `_esc_run_primed/_esc_undo_primed`，作用于该槽 tid；
   - `_submit` / `_route_slash`（L1231-1331）/ `_cancel_active` 一律从全局 `active_tid`
     改为**焦点槽 tid**；
   - 现有 `side_pill`（L236-241「← 回主线」）挪到右槽头部，点击 = close_side。
3. **事件归属（UiBridge）**：所有信号首参 = thread_id；`side-` 前缀（或 panes 反查表）
   → 右槽，其余 → 左槽。状态行 / queue strip / HITL 卡片 / 队列 badge 严格 tid 路由，
   禁止跨槽归属。
4. **并发**：主线任务 running + 侧边会话聊天 = 两 graph 并发写同一 SqliteSaver；
   ticket 01 先行预检（GUI ADR-0011 后台续跑是部分先例；两可见槽的 HITL 卡片 /
   queue strip 归属需实测）。发现缺口只补 GUI 层 per-tid 防护，不动内核。
5. **零改动清单**：`src/commands.py`（open_side/close_side）、`src/permissions.py`
   （side state + SideTaskGuardMiddleware）、`src/streaming.py`、`src/gui/runtime.py`
   L280-322 presenter 全部不变；只改 `src/gui/main_window.py` 布局层 +
   `src/gui/input_bar.py` 实例化（类本身不改、两实例）。
6. **树/右键回归**：`◇ ` 前缀、右键「开/删侧边会话」语义不变（删除走 close_side）。
决策如需留档：ADR-0013（GUI 分屏布局与键位路由；docs/adr 当前止于 0012）。

## 测试决策
- 新增 `tests/test_gui_split.py`（offscreen Qt + `tests/gui_fakes.py` 假件）：
  - 开侧边会话时 splitter 双槽出现、右槽四件套与左独立（实例 identity 断言）；关侧边后右槽折叠、焦点回左槽；
  - Esc 三级槽隔离（右槽空闲单 Esc 不触发左槽 undo primed）；
  - slash 路由到焦点槽 tid；双 tid 并发流事件 → HITL 卡片 / queue strip 归属不串；
  - 两槽输入草稿独立。
- 回归：`test_gui_esc.py` / `test_gui_slash.py` / `test_gui_queue_strip.py` /
  `test_gui_input_bar.py` / `test_side.py` 全绿。
- 纪律：`QT_QPA_PLATFORM=offscreen`；无 tmp_path；全量 pytest 忽略预存 test_config×3；
  CI ubuntu offscreen exit-139 容错规则不变。

## Out of scope
- saved-side 持久化（codex 0.169+ 特性，内核无 saved-side 概念）；
- 多侧边槽（内核 side-exists 门控只有一个）；
- splitter 比例跨重启持久化（会话内拖动调整 = 原生 QSplitter 行为，in scope）；
- TUI 分屏（另一套 spec：tui-ux22）；
- 任何 kernel / commands / permissions / streaming 改动。
