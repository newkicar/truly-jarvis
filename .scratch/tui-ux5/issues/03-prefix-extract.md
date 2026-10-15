# 03 — 命令前缀提取与前缀规则写回（permissions 层）

**What to build:** `permissions.extract_command_prefix(cmd)`（首 token；shell 包装两级提取：cmd /c、powershell|pwsh -Command|-c、bash|sh -c、wsl -e）+ `approve_prefix(state, prefix)`（当前值为字符串规则时先升格 `{"*": 原值}`，再写回 `"<prefix> *": "allow"`）+ `commands.always_approve` 签名改 `(state, tool, args=None)`：execute+args → 前缀路径，文件工具 → 原整工具行为，无 args → 完全向后兼容。

**Type:** task
**Status:** done
**Blocked by:** 无

## 验收
- [ ] 单测 extract_command_prefix：裸 `git log` → "git"；`powershell -Command git log` / `cmd /c dir` / `bash -c "ls /tmp"` / `wsl -e whoami` → 包装解出真实首 token
- [ ] 单测 approve_prefix：字符串 "ask" → {"*":"ask","git *":"allow"}；已是 dict 直接追加；fnmatch 最后匹配胜出语义不变
- [ ] 单测 always_approve：不带 args 时行为与旧版逐字段一致

## 参考
ADR-0006。对标 codex：审批记忆按命令前缀（如 "git *"）而非整工具。

## Comments