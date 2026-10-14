# 03 — 输入框粘贴图片（剪贴板图像 → [Image #N] → 多模态 content）

**What to build:** PowerShell 读剪贴板图片落盘临时 PNG（零新依赖）→ 输入框插 [Image #N] 占位符 → 提交时生成 OpenAI 多模态 content（image_url data URL）；model.image_input 能力门（auto/on/off，默认 auto，auto=失败自动回落路径引用重发一次）；图片路径文本粘贴识别。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 04

## 验收
- [ ] src/clipboard_image.py：try_copy_clipboard_image() → %TEMP%\jarvis-clipboard-*.png | None（Windows PowerShell；Unix 尽力）
- [ ] looks_like_image_path() / image_to_data_url() / build_multimodal_content()（纯函数可测）
- [ ] PasteInput：无文本 + 有剪贴板图片 → 插 [Image #N] 并登记；图片路径文本粘贴同登记；提交后清空
- [ ] run_agent_turn user_input 放宽 str|list|None（透传 content）
- [ ] model.image_input=off → 占位符替换为路径引用文本；auto → image/vision 类 API 错误时回落路径引用重发一次（不写历史）
- [ ] 单测：占位符解析/构建、路径识别、data URL、配置门、turn 透传

## 参考
codex paste_image_to_temp_png：arboard 读剪贴板→PNG→tempfile keep（codex-clipboard-*.png）；Windows 兜底 PowerShell Get-Clipboard -Format Image；输入框插 [Image #N] 原子占位符；提交时读文件→>2048px 缩放→base64 data URL 注入。本项目转换：缩放不做（无 Pillow），改 >4MB 提示。
