# 09 — 会话回退

**What to build:** 用户能通过 `/sessions` `/history` `/replay <id>` `/fork <id>` 定位历史会话、从某个 checkpoint 重跑、或从历史节点分叉出新分支（保留原历史）。这是 Time Travel 的会话层，基于 LangGraph checkpointer 原生能力。

**Blocked by:** 08

**Status:** resolved

- [ ] `/sessions`：列出历史会话
- [ ] `/history`：查看当前会话的时间线（checkpoint 列表）
- [ ] `/replay <checkpoint_id>`：从历史节点重跑（invoke(None, prior.config)）
- [ ] `/fork <checkpoint_id>`：从历史节点分叉（update_state），保留原历史
- [ ] 会话回退后新会话延续正确
- [ ] 冒烟：创建若干轮对话 → history 可见 → replay/fork 可用
