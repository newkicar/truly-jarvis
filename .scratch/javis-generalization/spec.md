# JARVIS 泛化：项目根 + 文件体系 + TUI 输入辅助

**日期：** 2026-08-20  
**状态：** done（2026-08-20 收尾）  
**动机：** 用户反馈 JARVIS 用起来像「为 Obsidian 开发的插件」，而非通用个人 agent；且运行目录不能作为项目根（对标 OpenCode）。

---

## 三个问题 → 一条主线

| # | 用户问题 | 根因 | 解决方向 |
|---|----------|------|----------|
| **A** | 在任意文件夹运行，应把该目录当项目根 | `project_root()` / `load_config()` 写死为 `src/` 上级安装目录 | **项目根发现** + 配置分层 |
| **B** | `@` 弹出全是 vault，像 Obsidian 专用 | 补全只扫 `*.md`、vault 排序优先、vault 体量大 | **workspace 优先** + 多后缀 + 前缀路由 |
| **C** | `@` 不应阻止继续输入；`/` 应有命令建议 | Enter 劫持选中；无 slash 补全 | **非阻塞 overlay** + **命令注册表** |

**主线：** 先让 `/workspace/` 真正等于「用户当前在做的事」，再让 TUI 输入辅助服务 workspace-first 的通用 agent；vault 降为可选知识后端（`/vault/`），不是默认 UI。

---

## 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│  用户 cd 到任意目录，运行 javis / python -m src.main         │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
              discover_project_root(cwd)
         向上找 javis.json；找不到则 cwd 或提示 init
                            ▼
┌─────────────────────────────────────────────────────────────┐
│  配置分层                                                    │
│  · 全局：~/.javis/.env 或 JARVIS_HOME（API Key）             │
│  · 项目：{project_root}/javis.json（vault、permissions…）    │
│  · 开发：仍可从 truly_Javis/ 跑，行为与今天一致              │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────── CompositeBackend ───────────────────────────┐
│  /workspace/  → project_root（代码、脚本、任意项目文件）     │
│  /vault/      → javis.json obsidian_vault（可选，只读+Inbox）│
│  /memories/   → {project_root}/memory 或全局 memory         │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────── TUI 输入辅助（非阻塞）──────────────────────┐
│  @  → 建议列表（Tab 接受，Enter 发送，Esc 关 overlay）       │
│  /  → 命令建议（filter，Tab 补全）                           │
└─────────────────────────────────────────────────────────────┘
```

---

## 设计决策（预采纳）

1. **项目根 ≠ 安装目录**  
   - 安装目录只放引擎（`src/`、内置 `skills/`）。  
   - `project_root()` 改为运行时解析结果，缓存于 `Config.project_root`。

2. **vault 保留，但不占默认 UX**  
   - 知识库能力（RAG、wiki、researcher 查 vault）不变。  
   - `@` 默认候选来自 `/workspace/`；`@vault/` 显式进知识库。

3. **补全 overlay 不是模态**  
   - **Enter** = 发送消息（默认）。  
   - **Tab**（或 **→**）= 接受当前高亮建议。  
   - **Esc** = 仅关闭 overlay，不删输入。

4. **命令单一真相源**  
   - `commands.SLASH_COMMANDS` 供 TUI overlay、`/help`、单测共用；`dispatch_command` 行为不变。

5. **开发模式兼容**  
   - 在 `truly_Javis/` 内运行：project_root = 该 repo，与现行为一致。  
   - 不要求用户立刻迁移 global `.env`（P1 可先「项目内 .env 优先，否则回退安装目录」）。

---

## 分期

| 阶段 | 票 | 交付 |
|------|-----|------|
| **P0 根** | 01–03 | 任意目录项目根 + backend 指向正确 workspace |
| **P1 泛化** | 04 | @ 补全 workspace 优先、多后缀 |
| **P1 交互** | 05–06 | / 命令建议 + 非阻塞 Tab/Enter |
| **P2 文档** | 07 | ADR + 设计文档 + 启动文案 |

---

## 验收（整体）

- [ ] `cd D:\my-app && javis` 时 `/workspace/` = `D:\my-app`，agent 可 read/edit 该目录代码  
- [ ] TUI 输入 `@src` 出现 `/workspace/.../*.py`，而非满屏 vault  
- [ ] 输入 `@` 后继续打字、Enter 发送，不被强制选中  
- [ ] 输入 `/` 或 `/his` 出现 `/history` 等建议，无需先 `/help`  
- [ ] `pytest tests/` 全绿；`smoke_test --tui` 手动过 @ 与 /  

---

## 相关文档

- 现有：`.scratch/javis-roadmap/issues/07-at-completion.md`（将被 04/06  supersede 行为）  
- 新建：`docs/adr/0004-project-root-and-general-agent.md`（票 07）
