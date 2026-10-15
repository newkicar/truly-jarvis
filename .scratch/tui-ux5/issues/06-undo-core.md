# 06 — commands.undo（消息层撤回核心）

**What to build:** `commands.undo(agent, tid, n=1)`：history = get_state_history（旧→新）；input_idxs = source=="input"；无输入点 → 文案「没有可撤回」；k 次回退：idx=input_idxs[-1-k]，idx>0 → `agent.update_state(thread_config(tid, 父checkpoint), None)`（_rollback 同款原语）；idx==0（撤到空白）→ 外科式：head 状态 messages 中末条 HumanMessage 起全部 RemoveMessage(id=m.id)，`update_state(thread_config(tid), {"messages": [...]}, as_node="model")`（fork 先例）。纯消息层：不动文件/Inbox；HITL 悬挂随回退作废。

**Type:** task
**Status:** open
**Blocked by:** 无

## 验收
- [ ] 单测：三轮用户输入场景 undo 1 / undo 3 / undo 超出（撤到空白，as_node="model"）各一条
- [ ] undo 后 get_state history 边界与 /history 渲染一致
- [ ] 文案约定：「已撤回 N 条消息（仅消息层；文件未动）」

## 参考
ADR-0005。对标 codex 多次 Esc time travel / opencode /undo。

## Comments