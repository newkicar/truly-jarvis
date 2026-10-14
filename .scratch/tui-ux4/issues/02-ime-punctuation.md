# 02 — 中文标点全支持（快插面板 + 终端提示）

**What to build:** Ctrl+. 标点快插面板（OptionList ~24 高频中英文标点，Enter 插入输入框）+ conhost 环境启动提示（tui.ime_hint auto/on/off）。不造 IME。

**Type:** task
**Status:** done
**Blocked by:** 03

## 验收
- [x] PunctPanelModal：OptionList，Enter 插入当前聚焦输入框，Esc 关闭
- [x] Ctrl+. 绑定无冲突（不与 ctrl+v/tab/ctrl+insert/ctrl+shift+c 等冲突；AltGr 保留）
- [x] conhost 探测（Windows 无 WT_SESSION/ConEmu*）→ dim 提示行；ime_hint=off 不提示
- [x] 单测：标点表、插入动作、conhost 探测函数

## 参考
codex：零 IME 代码——grapheme/unicode_width 边界处理 + keymap 保留 AltGr 给文字输入（Rust TUI 同样不解决 conhost 候选窗问题）。本项目转换：补一个「标点快插面板」把高频字符（…“”《》——）搬进来，加终端环境提示。


## Comments
- 2026-10-14 完成（worktree fdc7，分支 tui-ux4）：
  - 新增 `src/tui_punct.py`：PUNCT_ITEMS（25 个高频中英文标点，字符唯一、兼作 OptionList Option id，覆盖 …“”《》～—· 等）、`is_conhost_like()`（win32 且无 WT_SESSION/ConEmu* 环境变量）、`ime_hint_line(mode, conhost)`（off/on/auto，非法值回落 auto）
  - `src/tui.py`：`PunctPanelModal`（OptionList 快插，Enter 插入/替换选区，Esc 关闭）+ Ctrl+. 绑定 + on_mount conhost dim 提示行 + `_insert_punctuation` / `_ime_hint_mode`；新配置键 `tui.ime_hint`（默认 auto，缺省/非法值代码内回落 auto，jarvis.json 可不写）
  - Textual 8.x 兼容（顺带发现）：OptionList 构造器不再接受 can_focus 参数（类默认即可聚焦）→ 已去参；8.x 移除了 Screen.cancel 内置动作 → modal 需自行定义 `action_cancel` 使 Esc 关闭（PunctPanelModal 已加；CopyPickerModal 的同类问题在 #01 补交中修复）
  - `tests/test_tui_punct.py` 9 项全绿（标点表唯一性/覆盖、ime_hint 五种模式、conhost 探测 4 分支、pilot：Ctrl+. 开面板→回车插入、选区替换、Esc 关闭）
