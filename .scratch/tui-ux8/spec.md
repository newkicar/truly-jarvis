# TUI 体验八（tui-ux8）：审批弹窗「放行」默认焦点

**Type:** bugfix（用户报告：「审批弹窗『放行』按钮应该是每次默认选中的，让用户直接按回车就可以审批通过，而不需要先选中它」）
**Status:** ready-for-agent
**Blocked by:** 无（HITL 审批 modal 三期已落地，本批是 TUI 层焦点默认值，零上游依赖）

## Problem Statement

`PermissionModal`（src/tui.py L171，ModalScreen）四按钮：放行 / 永久放行 / 拒绝 / 编辑参数，
**无显式 focus 调用**。Textual `App.AUTO_FOCUS="*"`（app.py L396；`Screen.AUTO_FOCUS=None`
回落到 app 值）使 modal 激活时焦点落在 **DOM 顺序首个可聚焦部件**：`#perm_box`
（VerticalScroll，`can_focus=True`，compose 顺序在 `#perm_buttons` 之前）——
Textual 8.2.8 实证 `app.focused == VerticalScroll(id='perm_box')`。

后果：审批 modal 打开后直接按 **Enter** 无任何效果（屏级 BINDINGS 只有 a/s/d/e/escape，
perm_box 无 enter 绑定），用户必须 Tab/点击到「放行」或记住 'a' 键——审批多一步操作，
且 Tab 一次误操作就落到高风险的「永久放行」。

## Solution

单工单（01）：`PermissionModal` 类体加一行 `AUTO_FOCUS: ClassVar[str] = "#btn_approve"`
（Textual 原生 `Screen.AUTO_FOCUS` 机制：`Screen._update_auto_focus` 中
`self.app.AUTO_FOCUS if self.AUTO_FOCUS is None else self.AUTO_FOCUS`——屏级值覆盖 app 的
`"*"`；激活路径 `self.focused is None` 时设 `widget.has_focus = True`）。效果：modal 激活即
聚焦「放行」，**单次 Enter 完成审批**（Button 类级 BINDINGS `enter→press` →
`Button.Pressed` → `on_button_pressed` → dismiss）。a/s/d/e/escape 绑定与 dismiss 契约不变。

## User Stories

1. 作为用户，审批弹窗打开时「放行」已选中（焦点框可见），直接按一次 Enter 即审批通过，
   不需要 Tab/点击。
2. 作为用户，不打算放行时，'s'（永久放行）/'d'（拒绝）/'e'（编辑参数）/escape（放弃）
   按键全部保留，Tab 也可移焦到其他按钮——默认焦点不改变任何非放行路径。
3. 作为用户，放行后本轮继续执行（decisions 经 `streaming.collect_interrupt_decisions`
   回注），回复正常出现在对话里。

## Implementation Decisions

- **用 `Screen.AUTO_FOCUS` 而非 `on_mount().focus()`**：Textual 原生的激活期焦点机制，
  `Screen._update_auto_focus()` 在 compose/激活时运行且「focused 为 None 才设焦」，
  无与 auto-focus 时序竞态；`on_mount` 显式 focus 可能先于/被 auto-focus 覆盖。
- **「放行」为默认焦点是产品决策**（高频操作，对标 codex/opencode 审批 UI 的默认接受语义）；
  「永久放行」保持必须显式按键——默认焦点不为提权操作降门槛。
- **dismiss 契约零改动**：`on_button_pressed` / `choose()` / `_wait_modal_dismiss` 原样，
  只改初始焦点位置；PrefixModal / EditParamsModal 不在本批范围。
- **测试查询基座**：Textual 8.2.8 中 modal 激活时 `App.query_one` 只搜默认屏子树
  （实证 `NoMatches: No nodes match '#btn_approve' on Screen(id='_default')`），
  modal 内部件必须从 `app.screen.query_one(...)` 查；红灯测试按此修正。

## Testing Decisions

- **红灯测试 1**（`tests/test_tui.py::test_permission_modal_default_focus_approve_button`）：
  HITL interrupt 触发 → 断言 `app.screen is PermissionModal` 且
  `pilot.app.focused is app.screen.query_one("#btn_approve", Button)`（报错带 focused 实际值）。
  修复前：focused = `VerticalScroll(id='perm_box')` → RED。
- **红灯测试 2**（`::test_permission_modal_enter_approves_directly`）：modal 打开后单次
  `pilot.press("enter")` → 断言 modal 已关闭 + 日志含 `approved-echo`（FakeAgent 第二次
  stream_events 出 reply，证明 decisions 送达）。修复前：Enter 落 perm_box 无效果、
  modal 不关 → RED。
- 回归面：`tests/test_tui.py` + `test_tui_turn.py` + `test_streaming.py` 全绿；
  全量 pytest 无新增失败（基线 557 绿 + 4 预存/flaky 失败，`--ignore=tests/test_rag.py`）。
- 纪律：不碰 `tmp_path`；本批纯 TUI 内存态，无需自建目录。

## Out of Scope

- 其他 modal（PrefixModal / EditParamsModal / 会话管理）——保持 auto-focus 默认语义。
- 按键绑定集合 a/s/d/e/escape（保留不变）。
- 「永久放行」作为默认焦点（高风险，必须显式按键）。
- CLI 路径（`--cli` 的 [y]/[n]/[e]/[a] 单行输入，焦点机制不涉及）。

## Further Notes

- 与 tui-ux5/6/7 关系：权限 modal 布局规约（内容 80%、按钮行固定底部）不动；
  本批只加一个 ClassVar + 一个 import。
- 根因（diagnosing-bugs Phase 3，探针实证）：**H1** `#perm_box`
  （VerticalScroll.can_focus=True）为 DOM 顺序首个可聚焦部件而胜出焦点；
  **H2**（焦点残留底层 #input）排除——modal 激活后 `app.focused` 探针值 = perm_box。
- 仓库强制要求：参考开源（codex/opencode 审批对话框默认接受语义）；Textual 8.x 无新 API
  （`Screen.AUTO_FOCUS` 为既有 ClassVar，已对照安装版源码 widgets/_screen.py 实证）。