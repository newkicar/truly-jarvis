# 02 — 双 pane 布局（50/50 条件渲染）

**What to build:** `#editor_frame` 消息区改为主消息区 Horizontal 双列：
- 左 pane = 现有 `#messages` / `#ai_stream` / `#status_spinner` / `#todo_panel` /
  `#input`，原位不动；
- 右 pane = 新容器（RichLog 族流式 log + spinner + PasteInput 族输入 +
  运行/队列 badge），默认 `display: none`，按 side_active 条件渲染；
  v1 不含 todo panel / 图片条；
- 无 side 时左 pane 占满宽，布局与现状逐项一致（回归不变）；
  close_side 触发右 pane 消失 + 焦点回左 `#input`。

**Blocked by:** 01

**Status:** ready-for-agent

- [x] side_active 时右 pane 出现，左右 50/50（离屏几何断言）
- [x] 无 side 布局现状：test_tui / test_tui_log 回归全绿
- [x] 两 pane widget 实例 identity 独立（非共享断言）
- [x] close_side 后右 pane 收起、焦点回左 `#input`