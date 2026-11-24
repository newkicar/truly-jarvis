# 04 — 模型侧 goal 工具 ×3（仅主代理）

**What to build:** 主代理注入 `create_goal` / `complete_goal` / `get_goal` 三工具（启动时一次性注入，MCP 同款注入位；子代理不含）；create 重复失败，complete 必须附审计证据。

**Blocked by:** 02

**Status:** done

## 背景

- 模型需知目标（get）、声明目标（create）、标记完成（complete）；complete 是唯一 complete 写路径；pause/resume 是人类命令面，不给模型。

## 范围

- [x] `create_goal(objective, max_turns?)`：已有未完成 goal → 返回失败引导（一会话一目标）
- [x] `complete_goal(audit_evidence)`：无证据 → error；成功 → 翻 complete、记 audit_evidence + completed_at
- [x] `get_goal`：返回 objective/status/turns_used/max_turns/剩余
- [x] 注入契约：agent.py 主代理含 3 工具；researcher / knowledge_keeper / config_agents 自定义子代理 spec 不含（sanitize 子代理断言同款）
- [x] 工具单测：重复 create / 无证据 complete / get 返回 shape

## 非目标

- 不做 pause/resume 工具；不做模型侧 prompt 注入（续跑 prompt 走回合输入）
