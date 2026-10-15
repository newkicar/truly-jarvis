# ADR-0006: 「永久放行」= 命令前缀规则（对标 codex execpolicy）

**状态:** 已接受（2026-10-15）

## 背景

HITL 的「永久放行」现在对 execute 是一刀切（写回 `"execute": "allow"`，全命令放行），粒度太粗。codex 的审批模型 = PrefixRule（token 前缀 + 决策）+ HeuristicsFallback（未命中规则时的内置安全命令启发式）。JARVIS 已有全部底座：规则集 dict（fnmatch、最后匹配胜出）、when 谓词共享 state 引用、apply_permission_override、current_permissions → dump_permissions_json 写回 javis.json。缺的只是「从命令提取前缀 + 按前缀写回」这一段。

## 决策

1. **execute 的永久放行 = 写回命令前缀规则**：`"<prefix> *": "allow"`（并入该工具现有规则集 dict；字符串规则先升格为 `{"*": "ask"}` 再加前缀条）。前缀提取：默认首个空白分隔 token；shell 包装命令（`cmd /c`、`powershell -Command`/`-c`、`pwsh -Command`/`-c`、`bash -c`、`sh -c`、`wsl -e`）自动提两级。codex 式 token 交替语法（`a|b|c`）本期不做（fnmatch 规则集已可扩展）。
2. **Modal 交互**：execute 的「永久放行」弹前缀编辑框（自动提取值预填，用户可改，如把 `git *` 收紧为 `git status *`）；确认后才写回 jarvis.json 并即时生效（state 引用共享，无需重建 agent）。文件工具（write/edit/delete）保持整工具级永久放行不变。
3. **只读命令启发式表（codex HeuristicsFallback 对标）**：内置保守安全表（Get-Date/whoami/Get-Location/ls/dir/Get-ChildItem/Get-Content/git status/git log/git diff/Get-Process/tasklist/echo/hostname/pwd 等）；**默认关**（`permissions.heuristics: false` 缺省即关，守住「不配置即审批」安全底线），用户显式开启后：动作解析结果为 ask 且 execute 命令命中表 → 自动 allow（表优先级最低，规则与 hooks 仍先于它）。

## 被否决的选项

- **整工具 allow（现状）**：`git push --force` 也会免审，粒度事故。
- **前缀默认开启发式表**：与「默认全审批」的项目安全基调冲突；表内容跨 OS（PowerShell/cmd）难以穷举安全，留给用户显式开。
- **token 交替语法**：使用频率未证实，先不做，规则集天然可扩展。

## 影响

- 变更：`permissions.py`（extract_command_prefix / approve_prefix / 启发式表 / state["heuristics"] / current_permissions 携带 heuristics 键）、`commands.always_approve`（execute 带 args 时走前缀路径）、TUI PermissionModal「永久放行」→ PrefixModal（execute）或原行为（文件工具）。
- jarvis.json `permissions` 段新增可选键 `heuristics`（bool，缺省 false）；execute 规则集形态示例：`{"execute": {"*": "ask", "git *": "allow"}}`。
- 测试：前缀提取矩阵、规则集升格、写回格式、启发式开关、TUI PrefixModal 流。