# 04 — Inbox 边界 ADR 与设计文档同步

**What to build:** 将 Inbox 唯一写入口、项目内快照、会话回退语义、vault `.gitignore` 约定写入 ADR 与设计文档，使后续会话无需重读 grilling 记录即可理解边界。

**Blocked by:** 03 — 会话 /rollback 还原 Inbox

**Status:** done

- [ ] 新建 ADR（`docs/adr/0002-inbox-only-write-and-snapshots.md` 或下一编号）：决策、被否决方案（vault git commit）、与 CONTEXT.md 术语对齐
- [ ] 更新 `docs/specs/2026-08-15-javis-design.md` §10.4 / 三期可选项：Inbox 快照与回退已落地
- [ ] 更新 `.scratch/javis-implementation/map.md` 的 Not yet specified：Inbox 归档仍为人工；vault 全库回退仍为可选未来项
- [ ] `AGENTS.md` / `CLAUDE.md` 交付清单补充 Inbox 守卫与快照模块（若有新模块名）
