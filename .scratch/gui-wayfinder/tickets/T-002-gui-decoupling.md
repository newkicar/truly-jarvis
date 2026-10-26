---
id: T-002
title: agent 类项目 GUI 的 runtime/UI 解耦先例
labels: [wayfinder:research]
status: open
assignee: uida0712
blocked_by: []
---

# T-002 · agent 类项目 GUI 的 runtime/UI 解耦先例 [wayfinder:research]

## Question
agent/LLM 类 GUI 产品的 "runtime（agent）与 UI 解耦" 有哪些先例：
- codex（desktop / CLI / 云）
- opencode（serve + 多客户端，事件协议共享）
- LM Studio / Chatbox / Jan（本地推理 GUI + agent 能力）
- Continue / Roo Code（IDE 扩展作为 agent 客户端）
- LangSmith managed deep agents 官方 React useStream 模式

关注点：
1. 事件协议形状（stream 事件 + HITL 审批的跨层转递）
2. 会话/线程管理模型（多会话并发、切换、恢复）
3. 审批"编辑参数"的 GUI 表达（卡片 / 表单 / diff）

## 红线
- 先搜 GitHub 找先例，严禁闭门造车；涉及 deepagents 机制先查 langchain 官方文档最新版功能与语法。

## 输出
- 先例清单（带链接）+ 可照抄的协议要点 → .scratch/research/T-002-gui-decoupling.md
- 完成后：本票 status → done，同步 map.md
