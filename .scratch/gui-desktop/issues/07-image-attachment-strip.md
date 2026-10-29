# 07 — 图片附件条（粘贴 / 缩略图 / 放大 / 多模态提交）

**What to build:** 输入框上方图片附件条（GUI 原生形态，用户裁定：不做 TUI 的 `[Image #n]` 文本占位符）：Ctrl+V（剪贴板图）或粘贴图片路径文本 → 复用 `src/clipboard_image`（`try_copy_clipboard_image`/`looks_like_image_path` → temp 落盘）→ 附件条出现缩略图 chip（≈56×56 圆角 + ✕ 移除，点缩略图 → 无边框放大窗：等比 ≤80% 屏、Esc/点击关闭）；有附件才显示附件条。提交：附件随消息发——用户消息气泡内同样带缩略图（≈96px 高，可点放大）；载荷走 `build_multimodal_content`（OpenAI 多模态 parts）作 `user_input` + `image_fallback_text`（路径引用）作 `user_input_fallback`，`run_agent_turn` 既有 `model_image_input="auto"` 拒图回落语义不变。

**Blocked by:** 03（对话区与输入区：输入框与消息气泡已就位）

**Status:** ready-for-agent

- [ ] 剪贴板图粘贴 → 附件条出现缩略图；点 ✕ 移除；点缩略图放大窗查看（offscreen 全流程）
- [ ] 粘贴图片路径文本（Explorer 复制路径）同等进附件条
- [ ] 发送带图消息：`user_input` = 多模态 parts（text + image_url），`user_input_fallback` = 路径引用文本（纯函数断言）
- [ ] mock 模式验证管线形状（图片不发给 mock 模型属预期）；`--real` 验真多模态
- [ ] 消息气泡内缩略图可点放大；附件条随发送清空
