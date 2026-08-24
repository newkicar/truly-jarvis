# JARVIS Codex Harness — 决策摘要

`Status: done`（2026-08-24 关票：01/02/03 全部实现并带测试，280 单测绿）

## 背景

OpenAI 开源 [codex](https://github.com/openai/codex)（`codex-rs/`）。JARVIS 与 Codex 产品定位不同（个人心智 + vault vs 编码 agent + 沙箱），但 harness 工程上有可对标的四层：

1. **可观测**：effective config / session 健康  
2. **会话卫生**：失败 turn 不污染 checkpoint  
3. **交互 replay**：HITL 只 replay pending  
4. **审批扩展**：hook 先于 Modal  

## 决策（so far）

- **学形状，不搬家**：保持 Python + deepagents + `commands.py` 公共层。  
- **02 与现有修复合并**：`commands.repair_stuck_thread` + `run_agent_turn` retry（`c682d3a`）是 02 的起点，不是平行方案。  
- **03 轻量 hook**：优先「外部脚本/命令 + JSON 决策」，不对标 Codex 全量 lifecycle hooks。  
- **不做沙箱**：`LocalShellBackend` + HITL 足够；沙箱 escalation 仅作未来 ADR 候选。

## 票序与依赖

```
01 /doctor + config layers
 └─► 03 permission hooks（doctor 可展示 hook 加载结果）
02 turn finalize + pending HITL replay（可与 01 并行；依赖 repair 已有代码）
```

## 参考链接

- Codex orchestrator: https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/orchestrator.rs  
- Codex pending replay: https://github.com/openai/codex/blob/main/codex-rs/tui/src/app/pending_interactive_replay.rs  
- JARVIS 已有：`src/commands.py`（repair）、`src/streaming.py`、`src/permissions.py`
