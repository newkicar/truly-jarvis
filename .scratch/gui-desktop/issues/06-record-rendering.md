# 06 — 对话记录渲染（工具行「＋ 详情」+ 回放持久 + 思考块）

**What to build:** 对话区消息记录的渲染层正式化（TUI 已知问题①③ + 回放持久在 GUI 对标实现）：工具调用行 = 一行摘要（✓/✗ + 名称 + 参数截断）+「＋ 详情」展开钮（codex「+ Show details」对标，收起「－ 收起」），详情区 = 完整 args（JSON）+ 完整输出（等宽；文件类走 diff 渲染，复用 permission_preview 的 diff 生成）；**会话回放含完整工具记录**——pane 冷建（app 启动 / 首访旧会话）从检查点消息重建 user/AI 文本 + 工具行（AIMessage.tool_calls × ToolMessage 按 tool_call_id 配对，输出/错误态齐全，默认折叠）；**思考块**：模型 reasoning 内容以小字淡色块显示在回答上方（默认展开可折叠；字号/颜色与正文区分——用户裁定），思考通道 = 共享流层加**可选** `on_thinking` 回调键（5 键契约不动、CLI/TUI 不传=TUI 现状零行为变化；reasoning 块识别形状以实现时深验模型实际流为准）。

**Blocked by:** 03（对话区与输入区）

**Status:** done（2026-10-26）

- [ ] 工具行默认折叠；「＋ 详情」展开完整 args+输出，再点收起（长输出内滚）
- [ ] 重启 app 进旧会话 / 切走再切回：工具记录不丢（offscreen 双实例回放断言，原型实证手法）
- [ ] 思考块小字淡色渲染 + 折叠交互（fake 模型注入 reasoning 块验证）
- [ ] `on_thinking` 可选键：CLI/TUI 路径行为不变（既有 200+ 单测全绿回归）
