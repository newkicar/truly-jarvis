# 01 — 审批 modal「放行」默认焦点（Enter 直接通过）

**What to build:** `PermissionModal`（src/tui.py L171）打开后无显式 focus 调用 → 焦点落
DOM 顺序首个可聚焦部件 `#perm_box`（VerticalScroll.can_focus=True，Textual 8.2.8 实证
`app.focused = VerticalScroll(id='perm_box')`），Enter 无绑定不生效，用户须 Tab/点击/'a'
才能放行。在类体加一行：

```python
AUTO_FOCUS: ClassVar[str] = "#btn_approve"
```

- `src/tui.py` 头部增 `from typing import ClassVar`。
- 原生 `Screen._update_auto_focus` 机制（widgets/_screen.py）：屏级 `AUTO_FOCUS` 覆盖
  App 的 `AUTO_FOCUS="*"`；激活时 `self.focused is None` → `widget.has_focus = True`。
- BINDINGS a/s/d/e/escape 零改动；`on_button_pressed`/dismiss 契约零改动；
  PrefixModal / EditParamsModal 不动。
- 红灯测试（`tests/test_tui.py` 追加 2 条，harness 复用 `_FakeInterrupt` +
  `FakeAgent(reply="approved-echo", interrupted=True)` + `{"default": "ask", "tools": {}}`）：
  ① `test_permission_modal_default_focus_approve_button`：断言
  `pilot.app.focused is app.screen.query_one("#btn_approve", Button)`
  （Textual 8.2.8 App 级 query_one 只搜默认屏，须从 screen 查；报错带 focused 实际值）；
  ② `test_permission_modal_enter_approves_directly`：单次 `pilot.press("enter")` →
  modal 关闭 + 日志含 `approved-echo`。
  修复前 ① focused=perm_box、② modal 不关 → RED；修复后 GREEN。

**Type:** bug
**Status:** done (2026-10-18, commit 083124f)
**Blocked by:** 无

## 验收
- [x] 红灯测试 ① 绿（modal 打开即聚焦 #btn_approve）
- [x] 红灯测试 ② 绿（单次 Enter 完成审批 + 本轮继续出 reply）
- [x] 既有 TUI 测试无回归（test_tui / test_tui_turn / test_streaming）；全量 pytest 无新增失败
- [x] a/s/d/e/escape 绑定与 dismiss 契约不变

## Comments
2026-10-18 实施（commit 083124f）：
- 改动：`src/tui.py` `PermissionModal` 类体加 `AUTO_FOCUS: ClassVar[str] = "#btn_approve"`（Textual 原生
  `Screen._update_auto_focus`：屏级值覆盖 App 的 `AUTO_FOCUS="*"`，激活时 focused=None 才设焦，无
  on_mount 竞态）；头部加 `from typing import ClassVar`；`tests/test_tui.py` 追加 2 条红灯并修正
  查询基座（Textual 8.2.8 modal 激活时 `App.query_one` 只搜默认屏子树，modal 内部件须
  `app.screen.query_one`——首跑 RED 即此 NoMatches `on Screen(id='_default')`，探针确认后修正）。
- 结果：2/2 红灯绿（修复前 RED：focused=perm_box / 单次 Enter modal 不关）；
  test_tui + test_tui_turn + test_streaming 55 绿；全量 559 绿（557 基线 + 2 新增）+ 4 预存/flaky
  失败（3× test_config 预存 + 1× test_streaming drain 慢工具 flaky，单跑 1/1 过），无新增
  （`--ignore=tests/test_rag.py`）。

diagnosing-bugs 六阶段痕迹：
- Ph1 假设：H1 `#perm_box`（VerticalScroll.can_focus=True）为 DOM 顺序首个可聚焦部件胜出焦点；
  H2 焦点残留底层 `#input`。
- Ph2 RED：`test_permission_modal_default_focus_approve_button` / `test_permission_modal_enter_approves_directly`
  修复前红（首跑暴露 App 级 query 基座问题，探针修正后 = 焦点断言红）。
- Ph3 根因确认 = H1：探针实证 modal 激活后 `app.focused = VerticalScroll(id='perm_box')`（非 #input，
  H2 排除）；机制链 = `App.AUTO_FOCUS="*"` + 屏级 AUTO_FOCUS 缺省回落 + Modal 无显式 focus。
- Ph4 GREEN：类体单行 `AUTO_FOCUS: ClassVar[str] = "#btn_approve"`，2/2 红灯转绿。
- Ph5 回归：三文件组合 55 绿；全量无新增失败。
- Ph6 教训：Textual 8.2.8 modal 激活时 App 级 `query_one` 只搜默认屏子树（modal 内部件一律从
  `app.screen` 查）；「激活即默认焦点」用屏级 `Screen.AUTO_FOCUS`（原生机制、无时序竞态）优于
  on_mount 显式 focus；按键绑定行为以安装版 `widgets/_button.py` 为准（enter→press，无 space）。