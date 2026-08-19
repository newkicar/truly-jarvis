# 07 — 文档与 ADR（通用 agent + 三盘文件）

**What to build:** 新增 `docs/adr/0004-project-root-and-general-agent.md`；更新设计文档 §3/§11、CONTEXT.md、README 启动说明；关闭本 effort map。

**Blocked by:** 03, 06

**Status:** done

## ADR 要点

- **项目根**：cwd 发现，对标 OpenCode  
- **三盘模型**：`/workspace/` 通用项目，`/vault/` 可选 Obsidian，`/memories/` 偏好  
- **TUI**：workspace-first `@`，非阻塞补全，`/` 命令建议  
- **被否决**：删除 vault、@ 仅 md、Enter 强制选中

## 范围

- [ ] `docs/adr/0004-*.md`  
- [ ] `docs/README.md` ADR 索引  
- [ ] `docs/specs/2026-08-15-javis-design.md` 使命表述微调（通用 agent，知识库为能力之一）  
- [ ] `CONTEXT.md` 增加「项目根 / workspace」术语  
- [ ] `AGENTS.md` / `README.md` 启动与 @ 说明  
- [x] `.scratch/javis-generalization/map.md` → `Status: done`

## 验收

- 文档与实现一致，无「无 GPS 当轮说明」等已废弃 location 表述冲突
