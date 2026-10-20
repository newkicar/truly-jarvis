# 03 — PrefixModal 对齐（默认焦点 + 禁 select_on_focus + 容器 can-focus:no）

**What to build:** PrefixModal（src/tui.py L292）与 tui-ux10 对齐：

- 类体 `AUTO_FOCUS: ClassVar[str] = "#prefix_input"`（execute 审批按 s 打开前缀框
  即聚焦，直接可改；tui-ux8 #01 同款原生 Screen.AUTO_FOCUS 机制）。
- `Input(self.default_prefix, id="prefix_input", select_on_focus=False)`——
  Input 默认 select_on_focus=True（_input.py L368）= 点击即全文选中灰态 + 首键整值替换，
  前缀框同款病灶，参数规避（Input 保留 1 行，不需多行通道）。
- CSS `#prefix_box` 加 `can-focus: no`（工单 02 同款，容器不抢焦点）。
- 测试：execute 审批按 `s` → `pilot.app.focused is app.screen.query_one("#prefix_input", Input)`
  （既有 `test_permission_modal_s_opens_prefix_modal_for_execute` L142 流程上加断言或新增）。

**Type:** bug
**Status:** needs-triage
**Blocked by:** 无（与 01/02 平行，CSS 三容器 can-focus 在 02 已做，本票只做 PrefixModal 自身）

## 验收
- [ ] s 打开 PrefixModal 即聚焦 #prefix_input 绿
- [ ] select_on_focus=False / can-focus:no 落位
- [ ] 全量无新增失败

## Comments
