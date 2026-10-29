---
id: T-005
title: 整体迁移范围裁定与 TUI 共存策略
labels: [wayfinder:grilling]
status: done
assignee: uida0712
blocked_by: []
decided: 2026-10-26
---

# T-005 · 整体迁移范围裁定与 TUI 共存策略 [wayfinder:grilling]

> HITL 票：用户裁定（2026-10-26），代理不代替决定。

## 裁定（用户已确认）
- **TUI 正常保留**：不删除、不改动行为，作为有代码基础用户的通道。
- **GUI 客户端为额外形态**：给小白（无编程基础同事）使用，与 TUI 并行。
- 首发范围 = 整体迁移：GUI 客户端须与 TUI 全能力对齐（驱动 T-006 与 spec 范围）。
- 部署形态：单机客户端 exe，谁下载谁使用，不配服务器；LLM 各自配置（公司 OpenAI 兼容网关或第三方）。

## 子问处置
- (a) TUI 与 GUI 共存还是被 GUI 完全替代 → **定案：共存，TUI 保留为开发者通道**。
- (b) 非程序员默认值（隐藏命令面板 / 审批按钮放大 / 工具调用折叠）→ 留 spec 阶段（结合 T-002 审批卡片先例结论）。
- (c) Ollama/RAG 与定时任务可选依赖缺失时的降级策略 → 留 spec 阶段。
- (d) 同机 GUI/TUI 并发模型与 SqliteSaver 锁竞争 → 结合 T-002/T-004 研究结论，spec 时定。

## 输出
- 裁定结果已写入本票；map.md "Decisions so far" 同步行待 4 份研究收齐后统一补录并本地 commit。
- 驱动 T-006：GUI 骨架原型范围 = 聊天 + 审批卡片 + 会话侧栏（整体对齐 TUI）。
