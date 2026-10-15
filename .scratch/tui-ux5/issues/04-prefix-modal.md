# 04 — PrefixModal（前缀可编辑）+ Modal 接线 + CLI

**What to build:** tui.py 新 PrefixModal（单 Input 预填 `extract_command_prefix(inv.path)` + 说明行「将写回: "<prefix> *": allow（jarvis.json）」+ 确认/取消，按 01 规约布局）；PermissionModal「永久放行」btn_always/'s' 分流：execute → push PrefixModal（确认后 approve_prefix + dump_permissions_json 写回），文件工具 → 原 always_approve 流程；CLI `on_always_approve` 传 args（execute 时提示输入/确认前缀）。

**Type:** task
**Status:** open
**Blocked by:** 01, 03

## 验收
- [ ] PermissionModal 永久放行 execute → PrefixModal；前缀可改；确认 → state + jarvis.json 双写
- [ ] 文件工具（write_file/edit_file/delete）永久放行路径与现状一致
- [ ] CLI 'a' 路径 execute 场景传 args 走到前缀逻辑
- [ ] 单测：分流逻辑 + PrefixModal mount

## Comments