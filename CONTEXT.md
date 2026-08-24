# JARVIS

通用个人 agent：在哪运行，哪就是当前项目（`/workspace/`）；Obsidian vault 是可选知识后端（`/vault/`），Inbox 是它对 vault 的主要写入口。

## Language

**Vault**：
用户的 Obsidian 知识库整体（可选后端，`javis.json` 的 `knowledge_base` 配置路径；留空或删除该键 = 本次会话没有 `/vault/`）。JARVIS 可只读检索其中任意笔记；除下方可写目录外不得创建、修改或删除文件。
_Avoid_: 知识库根、整个仓库（当实际只指可写区时）

**Inbox**：
Vault 内 JARVIS 可写的暂存文件夹（`/vault/Inbox/`）。新笔记先落在这里，等人审核。JARVIS 可在审批后新建、修改或删除其中已有文件。
_Avoid_: 草稿箱、dump、scratch（当指这条边界时）

**Reports**：
Vault 内 JARVIS 可写的报告输出目录（`/vault/Reports/`）。用于资讯整理、日报/周报等结构化报告落盘。同样需 HITL 审批；Vault 其它路径（Inbox/Reports 以外）即使审批通过也不得写入。
_Avoid_: 与 Inbox 混称（Inbox=待审核沉淀，Reports=报告输出）

**可写 Vault 目录**：
JARVIS 允许 `write_file` / `edit_file` / `delete` 的 vault 路径仅限 `/vault/Inbox/` 与 `/vault/Reports/`；写入前会记快照，会话 `/rollback` 可还原。

**Inbox 快照**：
每次成功写入 Inbox 前，在 JARVIS 项目里记下该文件的写前副本，并与当时的会话检查点、写入方的 thread_id 对齐。会话 `/rollback` 只还原该会话写过的 Inbox 文件（含覆盖你在 Obsidian 里对同一文件的手改），并列出将还原或删除的路径；定时任务的写入不在会话回退范围内。
_Avoid_: vault 回退、git 快照（当实际只还原 Inbox 时）

**沉淀**：
JARVIS 把值得长期保留的知识写成新笔记并放入 Inbox。
_Avoid_: 归档、写入知识库（太宽，会让人以为能写任意文件夹）

**归档**：
人在 Obsidian 里把 Inbox 笔记挪到 Vault 其它文件夹。这不是 JARVIS 的动作。
_Avoid_: 沉淀、移动、promote

**项目根（project root）**：
用户运行 JARVIS 时的工作目录上下文。从 cwd 向上找 `javis.json` 确定；`/workspace/` 虚拟路径映射到此目录。安装目录（引擎代码）≠ 项目根。
_Avoid_: 把 `truly_Javis/` 安装路径当作唯一 workspace、写死绝对路径进 prompt

**Workspace**：
CompositeBackend 路由 `/workspace/`，根目录 = 项目根。承载代码、脚本、配置与内置 `skills/` 虚拟路径；主代理在此具备 `execute`。
_Avoid_: 与 vault 混称（workspace = 当前做的事，vault = 可选笔记库）

**系统上下文**：
本机日期、时间与 IP 推算城市等「随环境变化」的信息。**会话启动时**仅把**当天日期 + 星期**写入 system prompt（不含时分秒）。问精确时间、所在城市时用主代理 `execute` 读本机，**不**写死 `javis.json` 或 profile，**不**读 user-profile 找所在地。
_Avoid_: 在 javis.json 里配 location、读 user-profile 找所在地、为问时间单独做专项 skill/工具

## 文档

- 使用与命令：[`README.md`](README.md)
- 完整设计：[`docs/specs/2026-08-15-javis-design.md`](docs/specs/2026-08-15-javis-design.md)
- ADR：[`docs/adr/`](docs/adr/)（TUI、Inbox 边界、项目根等）
