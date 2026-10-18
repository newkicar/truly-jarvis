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
**Status:** ready-for-agent
**Blocked by:** 无

## 验收
- [ ] 红灯测试 ① 绿（modal 打开即聚焦 #btn_approve）
- [ ] 红灯测试 ② 绿（单次 Enter 完成审批 + 本轮继续出 reply）
- [ ] 既有 TUI 测试无回归（test_tui / test_tui_turn / test_streaming）；全量 pytest 无新增失败
- [ ] a/s/d/e/escape 绑定与 dismiss 契约不变

## Comments
（实施后补：commit 记录 + diagnosing-bugs 六阶段痕迹）