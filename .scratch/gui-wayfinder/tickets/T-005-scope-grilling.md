---
id: T-005
title: 整体迁移范围裁定与 TUI 共存策略
labels: [wayfinder:grilling]
status: open
assignee: 待用户裁定
blocked_by: []
---

# T-005 · 整体迁移范围裁定与 TUI 共存策略 [wayfinder:grilling]

> HITL 票：需用户逐条裁定（grilling skill 流程），代理不代替决定。

## 裁定清单（逐条）
能力去留/默认值：流式聊天、审批卡片、会话侧栏、plan-act 模式、yolo 模式、undo、
snapshot / replay / fork / rollback、scheduler 定时任务、vault+RAG、skills + /use、
/compact、MCP、/doctor、主题。

## 子问
(a) TUI 与 GUI 共存还是被 GUI 完全替代（CLI/TUI 是否保留为开发者后门）？
(b) 非程序员默认值差异：隐藏命令面板？审批按钮放大？工具调用折叠？
(c) Ollama/RAG 与定时任务 = 可选依赖，缺失时降级策略？
(d) GUI/TUI 同机共存的并发模型与 SqliteSaver 锁竞争（结合 T-002/T-004 研究结论）。

## 输出
- 裁定结果写入本票 + map.md 的 Decisions so far；驱动 T-006 范围。
