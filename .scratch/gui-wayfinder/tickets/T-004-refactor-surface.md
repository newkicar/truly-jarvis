---
id: T-004
title: 事件边界最小重构面（读本仓）
labels: [wayfinder:research]
status: open
assignee: uida0712
blocked_by: []
---

# T-004 · 事件边界最小重构面（读本仓）[wayfinder:research]

## Question
读本仓（worktree 副本）src/commands.py、src/streaming.py、src/tui.py，评估支持"第二个客户端（GUI）"的最小重构面：
- HITL call_from_thread 推送路径（Textual 耦合点）
- TurnPresenter / turn gate / FIFO 排队（Textual 线程）
- stream_events（v3）消费契约
- 枚举 GUI 可直接挂（零重构）的部分：commands + stream_events + permissions resume 契约
验收线 = **TUI 零改动**（既有测试全绿）。

## 红线
- 先读代码再看先例；提重构方案前先查 deepagents/langgraph 官方文档有没有现成 seam（middleware / hooks / 事件通道）。

## 输出
- 重构点清单（文件/函数级）+ GUI 消费架构提案 → .scratch/research/T-004-refactor-surface.md
- 完成后：本票 status → done，同步 map.md
