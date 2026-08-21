# 07 — TUI 对话区 Rich 渲染 + 真实鼠标选区（对标 OpenCode）

**What to build:** 在保留 Markdown / 彩色消息样式的前提下，让对话区支持稳定鼠标拖选与复制（对标 OpenCode TUI 面板体验）。**排期：最后实现**（当前先用序号命令与侧边栏快捷键绕开）。

**Type:** task

**Status:** done

**Blocked by:** 无

## 背景

- 当前对话区为 Textual `RichLog`（`CopyableRichLog` 仅补了 `get_selection()`），内容是 Rich 渲染后的 **Strip 画面**，不是字符网格。
- CMD / conhost 下拖选不稳定；Ctrl+Shift+C 易与终端行为冲突。
- OpenCode 使用 OpenTUI：选区是一等能力（`copy_on_select`、格子坐标、`Selection.copy()`），与 RichLog 路径不同。

**短期已做（不替代本票）：**

- `/sessions`、`/history` 序号 + `/delete-session N`、`/replay N`、`/fork N`
- `/copy-session`、侧边栏 Y/D、Ctrl+Insert
- `CopyableRichLog` + Win32 剪贴板辅助

## 目标（方案 2 — 中等复杂度）

保留现有视觉（竖线、Markdown、工具行 muted、流式 `#ai_stream`），底层增加**真实文本/选区层**：

1. 消息追加时同步维护**纯文本缓冲**（或与渲染层映射的行表）。
2. 鼠标拖选按**内容坐标**高亮，而非仅依赖 RichLog 默认行为。
3. 松开鼠标：复制到系统剪贴板（Windows 走 Win32；可选 copy-on-select 配置）。
4. 流式输出期间：选区策略明确（锁定/清除/跟尾滚动），避免 OpenCode 曾出现的「copy 后无法再选」类 bug。
5. CMD 与 Windows Terminal 分别冒烟；文档说明与 OpenCode `mouse: false` 的取舍。

**明确不做（本票）：** 换 OpenTUI 全栈重写（方案 3）。

## 非目标

- 不要求与 OpenCode 像素级一致。
- 不替代序号命令（序号仍保留为无鼠标时的快捷路径）。

## 验收

- [x] CMD 下对话区可拖选任意可见文本（含 session id、/history 行、AI 回复片段）。
- [x] 复制后可在记事本粘贴；Ctrl+Insert / 配置快捷键可用。
- [x] Markdown 消息仍可读（标题、列表、代码块基本不退化）。
- [x] 流式生成结束后选区行为可预期；单测 + TUI 冒烟更新。
- [x] `AGENTS.md` / TUI_HELP 补充选区说明。

## 参考

- 代码：`src/tui.py`、`src/tui_log.py`、`src/tui_format.py`
- OpenCode：`tui.json` 的 `mouse` / `copy_on_select`；OpenTUI `Selection` 实现
- 对话结论：方案 1（只读 TextArea）简单但丢样式；方案 2 为本票；方案 3 过大

## Comments

- 2026-08-21：用户确认方案 2 写入待办，最后实现。
