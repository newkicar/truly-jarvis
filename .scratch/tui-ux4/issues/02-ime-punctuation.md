# 02 — 中文标点全支持（快插面板 + 终端提示）

**What to build:** Ctrl+. 标点快插面板（OptionList ~24 高频中英文标点，Enter 插入输入框）+ conhost 环境启动提示（tui.ime_hint auto/on/off）。不造 IME。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 03

## 验收
- [ ] PunctPanelModal：OptionList，Enter 插入当前聚焦输入框，Esc 关闭
- [ ] Ctrl+. 绑定无冲突（不与 ctrl+v/tab/ctrl+insert/ctrl+shift+c 等冲突；AltGr 保留）
- [ ] conhost 探测（Windows 无 WT_SESSION/ConEmu*）→ dim 提示行；ime_hint=off 不提示
- [ ] 单测：标点表、插入动作、conhost 探测函数

## 参考
codex：零 IME 代码——grapheme/unicode_width 边界处理 + keymap 保留 AltGr 给文字输入（Rust TUI 同样不解决 conhost 候选窗问题）。本项目转换：补一个「标点快插面板」把高频字符（…“”《》——）搬进来，加终端环境提示。
