# 10 — 放开文件夹访问限制，不限于预定义虚拟路径

**What to build:** 移除 /workspace/、/vault/、/memories/ 等虚拟前缀对文件工具的硬限制，允许代理访问任意磁盘路径（仍走审批）。

**Type:** task

**Status:** todo

**Blocked by:** 无

## 背景

- 当前文件工具（ls/read_file/write_file/edit_file/glob/grep）只能通过虚拟前缀路由：`/workspace/`（项目根）、`/vault/`（Obsidian）、`/memories/`（记忆）、`/skills/`、`/builtin-skills/`。
- 虚拟前缀之外的磁盘路径对文件工具**不存在**——模型只能用 `execute`（shell）来访问外部路径，但 execute 走审批且输出不可控。
- 用户实际需求：代理需要读取项目外的配置文件、数据文件、其他项目代码等，当前必须手动复制到项目内或用 shell 绕过。
- `InheritedEnvShellBackend._virtual_prefix_error` 在 shell 命令中拦截虚拟前缀（防止模型把 `/workspace/` 当 shell 路径），这个保护仍然需要保留。

## 目标

### 1. 文件工具支持任意路径

- `ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep` 接受**绝对路径**或**相对路径**（相对于 `cwd`）
- 路径不再必须以虚拟前缀开头
- CompositeBackend 的 `default` 从 `InheritedEnvShellBackend` 改为 `FilesystemBackend(root_dir="/")`（根目录），或改为无 root 限制的模式
- 虚拟前缀路由仍然保留（兼容现有 prompt 约定），但不再是唯一入口

### 2. 安全边界调整

| 机制 | 改动前 | 改动后 |
|------|--------|--------|
| 文件工具路径 | 只能虚拟前缀 | 任意路径（绝对/相对） |
| shell 虚拟前缀拦截 | 拦截 `/workspace/` 等 | **保留**（shell 仍不应出现虚拟前缀） |
| vault 写保护 | `/vault/` 只写 Inbox/Reports | 保留（vault 仍是特殊区域） |
| HITL 审批 | write_file/edit_file 默认 ask | 保留（外部路径写操作仍需审批） |
| 权限 deny 规则 | 可 deny 特定工具 | 可 deny 特定路径模式（已有） |

### 3. Prompt 约束更新

- 移除系统提示中的「文件路径只用 `/workspace/`（项目）、`/vault/`（Obsidian）……」限制
- 改为「文件工具接受任意磁盘路径；`/workspace/`、`/vault/` 等前缀仍可用作快捷方式（自动映射到对应目录）」
- JARVIS_HARNESS_SUFFIX 中的虚拟路径边界说明同步更新

### 4. 相对路径解析

- 相对路径以 `config.project_root`（即 `/workspace/` 对应的真实路径）为基准
- 绝对路径直接使用
- 路径规范化：`..`、`~` 展开

## 非目标

- 不移除 vault 写保护（Inbox/Reports 限制仍有意义）
- 不移除 shell 虚拟前缀拦截（保护仍在）
- 不改变 execute 工具的行为（仍走审批）
- 不实现路径白名单/黑名单（用 permissions deny 规则替代）

## 验收

- [ ] `read_file /etc/hosts` 可读取（或任意非项目路径）
- [ ] `ls /tmp` 可列出（或任意非项目路径）
- [ ] `write_file /tmp/test.txt "hello"` 走审批（HITL ask）
- [ ] shell 命令中 `/workspace/xxx` 仍被拦截（虚拟前缀保护保留）
- [ ] `/vault/Inbox/test.md` 写入正常，`/vault/Other/test.md` 被 vault_guard 拦截
- [ ] 虚拟前缀快捷方式仍可用（`/workspace/src/main.py` 等价于 `src/main.py`）
- [ ] 单测覆盖新路径路由
- [ ] AGENTS.md 更新路径约束说明

## 参考

- 代码：`src/agent.py`（_make_backend、CompositeBackend 路由）、`src/shell_backend.py`（virtual_prefix_error）、`src/vault_guard.py`（vault 写保护）、`src/permissions.py`（路径 deny 规则）
- deepagents：CompositeBackend 的 `default` 后端逻辑

## Comments

- 2026-08-25：用户要求创建此票，放开对文件夹访问的限制。
