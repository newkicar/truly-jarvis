# JARVIS 文档

## 从这里读起

| 读者 | 文档 |
|------|------|
| 使用者 | 仓库根 [`README.md`](../README.md) |
| 领域语言 | [`CONTEXT.md`](../CONTEXT.md) |
| 架构与设计 | [`specs/2026-08-15-javis-design.md`](specs/2026-08-15-javis-design.md) |
| Agent 协作 | 仓库根 [`AGENTS.md`](../AGENTS.md) |

## 架构决策（ADR）

| ADR | 主题 |
|-----|------|
| [0001-jarvis-tui.md](adr/0001-jarvis-tui.md) | Textual TUI 选型、流式、审批 Modal；含 2026-08-19 体验增强 |
| [0002-inbox-only-write-and-snapshots.md](adr/0002-inbox-only-write-and-snapshots.md) | Vault 仅 Inbox 可写；项目内快照；会话 rollback |
| [0003-system-context-on-demand.md](adr/0003-system-context-on-demand.md) | 日期/时间 + IP 推算城市；结果导向主提示词；不写死 location |

## 实现跟踪（本地）

| 目录 | 说明 |
|------|------|
| `.scratch/javis-implementation/` | 一期–三期实现票 |
| `.scratch/javis-tui/` | TUI 专项票 |
| `.scratch/javis-roadmap/` | 后续路线（Inbox → TUI 体验 → 测试），**已关票** |

路线决策摘要： [`.scratch/javis-roadmap/map.md`](../.scratch/javis-roadmap/map.md)

## Agent 工作流

见 [`agents/`](agents/)：issue tracker、triage labels、domain docs 消费方式。
