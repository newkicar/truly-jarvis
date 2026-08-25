# 13 — 切换对话时加载历史记录到显示栏

**What to build:** 通过左侧栏点击切换会话时，显示栏应更新为该会话的历史消息（从 checkpoint 加载最近一轮的 assistant 回复），而非只显示「已切换到会话 xxx」。

**Type:** enhancement

**Status:** ready-for-agent

**Blocked by:** 无

## 背景

切换对话是「回到之前讨论过的某个话题」，用户期望立即看到那个对话的内容继续讨论，但当前只显示切换成功提示，显示栏仍是上一个会话的旧内容，需要用户手动 `/history` 回看。

## 验收
- [ ] 左侧栏点击任意会话 → 显示栏清空并加载该会话最近一轮 assistant 消息
- [ ] 加载的消息带 JARVIS 标题头（与流式输出格式一致）
- [ ] 无历史的会话显示「暂无历史」
- [ ] /new-session（带新 id）不触发历史加载（新会话无历史）

## 参考
- src/tui.py `_switch_session()` — 当前只写切换提示
- src/commands.py `list_history()` — 已有历史提取逻辑
- checkpoint 查询路径：`agent.get_state(configurable=thread_config(tid))`

## Comments

- 2026-08-26：用户反馈切换会话后显示栏内容与预期不符。
