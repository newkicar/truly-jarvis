---
id: T-006
title: GUI 骨架原型（聊天 + 审批卡片）
labels: [wayfinder:prototype]
status: claimed
assignee: uida0712（代理驱动，HITL 过稿）
blocked_by: [T-001, T-005]
---

# T-006 · GUI 骨架原型（聊天 + 审批卡片）[wayfinder:prototype]

> Blocked：T-001（框架选型）与 T-005（范围裁定）都完成定案后才可开工。

## Question
用 T-001 选定的框架，做最小可跑 GUI 骨架：
- 聊天流 + Markdown 流式渲染
- 审批四按钮卡片（放行 / 永久放行 / 拒绝 / 编辑参数，复用 permissions resume 契约）
- 会话列表（侧栏摘要，参考 TUI UX11）
接真实 stream_events / HITL 契约（真 LLM 或 mock），HITL 用户过稿。

## 纪律
- 原型 = throwaway 或 seed：TUI 主路径与既有测试零改动；验证状态模型与交互手感是否对（prototype skill）。

## 输出
- 可运行原型 + 过稿记录 → .scratch/prototype/（或用户指定目录）；过稿后驱动 to-spec。
