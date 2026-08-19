# JARVIS

个人知识代理：在 Obsidian vault 上检索与沉淀，项目目录承载记忆与工具，Inbox 是它对 vault 的唯一写入口。

## Language

**Vault**：
用户的 Obsidian 知识库整体。JARVIS 可只读检索其中任意笔记；除下方可写目录外不得创建、修改或删除文件。
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

**系统上下文**：
本机日期、时间与 IP 推算城市等「随环境变化」的信息。JARVIS **不在启动时**写进主 system prompt，也不把地址写死在 `javis.json` 或 profile；需要时通过 `get_system_context` 与 `system-context` skill 按需读取。时间来自本机时钟；城市来自公网 IP 地理定位（ISP 级，非 GPS）。
_Avoid_: 在 javis.json 里配 location、读 user-profile 找所在地、启动时注入「现在是…」

## 文档

- 使用与命令：[`README.md`](README.md)
- 完整设计：[`docs/specs/2026-08-15-javis-design.md`](docs/specs/2026-08-15-javis-design.md)
- ADR：[`docs/adr/`](docs/adr/)（TUI、Inbox 边界等）
