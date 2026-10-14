# 01 — TUI 对话复制（程序化复制 + 剪贴板级联）

**What to build:** /copy picker（最近 AI 回复 / 最近代码块 / 整段会话）+ Ctrl+Shift+Y 快捷键 + 剪贴板写入两级级联（Win32 重试→PowerShell）+ copy_on_select 默认 True。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 无

## 验收
- [ ] /copy 打开 CopyPickerModal（OptionList 三选项）；Ctrl+Shift+Y 同
- [ ] 最近代码块 = 最后一条 AI 文本中最后一个三反引号围栏（含围栏）
- [ ] 整段会话 = 当前 thread 历史 user/AI 渲染文本
- [ ] copy_text_to_system_clipboard 级联：Win32（重试 2 次）→ PowerShell Set-Clipboard
- [ ] JarvisApp._copy_on_select() fallback 改 True
- [ ] 帮助文案补 /copy、Ctrl+Shift+Y
- [ ] 单测：commands 新纯函数 + tui_log 级联（mock）+ config 默认值

## 参考
codex：Ctrl+O 复制最近 AI 回复 + /copy picker（整条/代码块）+ 剪贴板写级联（arboard→PowerShell→OSC52 100KB 上限）。本项目转换：Win32→PowerShell 两级（OSC52 在 Windows 端意义有限，不做）。

