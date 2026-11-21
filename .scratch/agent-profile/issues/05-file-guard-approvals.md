# 05 — 文件边界守卫 + approvals 权限 + 审计 JSONL

Status: ready-for-agent
Blocked by: 02

## What to build

1. `src/file_guard.py`：
   - `resolve_within(base, requested)->Path`：`Path.resolve()` 真实包含性，拦 `..` 与 symlink 逃逸；Windows 跨盘符=拒绝；UNC 处理；禁止字符串前缀判断；违例抛 `PathBoundaryError`；
   - `WorkspaceFileGuardMiddleware`（继承项目 `GuardMiddleware`，wrap/awrap 走基类）：经 `view.arg_value("file_path","path")` 拦 write_file/edit_file/delete；workspace_only=True 时读工具同界；未注册工具名 no-op 放行或 fail-closed（按 spec 定）；不使用 deepagents 自带 FilesystemPermission；
   - `permissions.approvals{execute,external_network,destructive_operations}`（缺省 required）→ 追加权限规则（execute→ask；delete→ask；external_network→网络工具 ask，与既有规则 deny-wins 合并）；歧义 = fail-closed；
   - 审计 JSONL `~/.jarvis/audit/permissions.jsonl`（sanitize：前缀/hash/摘要，绝不含完整 raw args）。
2. 测试：`tests/test_file_guard.py`（`../` 穿越 / 跨盘符 / UNC / symlink 穿越 / 未注册工具 / deny 调用 / 项目层试图放宽权限被拒；审计行不含 raw args）。

## Acceptance

- [ ] 目标套件全绿；
- [ ] 相关套件（permissions/vault_guard）vs 基线无新增失败；
- [ ] commit（UTF-8 message 文件）。
