# 12 — 新建对话时清空显示栏历史文本

**What to build:** 新建对话时（`/new-session` 或 Ctrl+N），显示栏应清空当前历史消息文本，只显示新会话的欢迎提示（JARVIS 就绪等），不再残留旧对话内容。

**Type:** enhancement

**Status:** ready-for-agent

**Blocked by:** 无

## 背景

新建对话是「重新开始」——用户期望看到干净的空白画布，但当前只追加一行「已开启新会话 session-xxx」，旧对话内容仍留在显示栏中，造成视觉混乱。

## 验收
- [ ] Ctrl+N 或 /new-session 后，显示栏旧消息清空
- [ ] 清空后显示 JARVIS 就绪欢迎提示
- [ ] 旧会话内容可通过 /history 回看（清空的是显示栏，不是 checkpoint）

## 参考
- src/tui.py `_adopt_thread()` — 当前仅追加「已开启新会话」文本
- src/commands.py `delete_session()` — 删当前会话路径也走 `_apply_command_result`

## Comments

- 2026-08-26：用户反馈新建对话后旧内容仍残留。
