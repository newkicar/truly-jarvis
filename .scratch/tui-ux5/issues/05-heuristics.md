# 05 — 只读启发式表（permissions.heuristics，默认 false）

**What to build:** `HEURISTIC_SAFE_COMMANDS` 小写元组（get-date、whoami、hostname、get-location、pwd、ls、dir、get-childitem、get-content、git status、git log、git diff、get-process、tasklist、echo）；`_action_for_args` 尾段：action=="ask" 且 tool=="execute" 且 state.get("heuristics") 且命令小写前 1–2 token 命中 → "allow"；`build_permission_interrupts` 读 jarvis.json `permissions.heuristics`（默认 False）入 state；`current_permissions` 仅 True 时带该键（dump_permissions_json 是整体替换 data["permissions"]，序列化/写回路径勿吞用户配置）。

**Type:** task
**Status:** open
**Blocked by:** 03

## 验收
- [ ] 单测：heuristics 关（缺省）→ 全部保持 ask
- [ ] 单测：开 → "Get-Date" → allow、"git status" → allow、"git push" → ask（两 token 表项）
- [ ] dump / current_permissions 往返：heuristics 键在用户配置中被保留
- [ ] jarvis.json 文档/帮助提及 `permissions.heuristics` 开法

## Comments