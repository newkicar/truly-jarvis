# 03 — Permission hooks（审批前扩展）

**What to build:** 在 HITL Modal 之前增加可配置 hook：对用户 gated 工具（execute/write/edit/delete）调用外部命令或脚本，返回 allow / deny / ask（fallback 到现有 Modal）。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** 01

## 背景

- Codex `hook_runtime::run_permission_request_hooks` 优先级：**Hooks → Guardian → User**。  
- JARVIS 仅有 `javis.json permissions` 对象规则 + Modal；改规则需编辑 JSON 或 always approve。  
- 用户场景：`git push` 永远 deny、`git status` allow、特定路径写 vault 前先跑自定义检查。

## 范围

- [ ] 配置形态（二选一或并存，实现时定）：
  - `javis.json` → `hooks.permission`: `[{ "match": "git push", "command": ["python", "hooks/deny.py"], ... }]`
  - 或 `~/.javis/hooks/permission/` 目录约定  
- [ ] Hook 输入：JSON stdin（tool name、args、path、thread_id）；输出：`{"decision":"allow"|"deny"|"ask"}`  
- [ ] 集成点：`permissions.py` 或 `streaming.collect_interrupt_decisions` 之前；**deny** 不弹 Modal，直接 ToolMessage error  
- [ ] 超时与失败：hook 失败 → 回落 `ask`（默认安全）  
- [ ] 单测：fake hook 脚本；match 规则；deny 不中断 graph 以外路径  
- [ ] `/doctor` 列出已加载 hook 数量与路径（依赖 01）  

## 非目标

- 不对标 Codex 全量 lifecycle hooks（pre_tool/post_tool 等）  
- 不做 Guardian LLM 自动审批  
- hook 不能绕过 `vault_guard` Inbox 写边界  

## 验收

- 示例 hook：`execute` + `git push` → deny，agent 收到明确 error  
- 示例 hook：`execute` + `git status` → allow，无 Modal  
- 未匹配规则仍走现有 HITL Modal  
- 文档：`README` 或 `docs/` 短节 + `javis.json` 示例片段  

## 参考

- Codex: `hook_runtime.rs`、`tools/approvals.rs`（Hooks 优先）  
- JARVIS: `src/permissions.py`、`src/streaming.py`
