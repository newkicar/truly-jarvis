# Map: JARVIS 实现路径

`Type: map`  `Status: open`

## Destination

把 JARVIS 从设计文档（`docs/specs/2026-08-15-javis-design.md`）走到可运行的实现，并分阶段推进：一期（主代理 + researcher 指定检索 + WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + javis.json + Tavily）→ 二期（动态子代理 fan-out + 定时检索 + 长期记忆 + git 文件回退）→ 三期（executor + skill/mcp 接口 + 增量 RAG）。

## Notes

- 领域：Python + deepagents 0.7.x + langchain-openai（opencode.ai/zen/v1, 模型暂用 `deepseek-v4-flash-free`，付费版待充值）
- 环境：Windows；conda env `thomas`（Python 3.12.9，`D:/AIPrograms/Annaconda/envs/thomas/python.exe`）；pip + requirements.txt；一期 git init
- 每个会话前必读：`AGENTS.md`、`docs/specs/2026-08-15-javis-design.md`、`docs/agents/*.md`
- 强制要求：实现前到 GitHub 找参考；用 docs-langchain MCP 核对 deepagents 最新语法
- 本 map 只产出决策与事实，不产出交付物（除非票面 Notes 另行说明）
- 范围确认：vault（`E:\Thomas\Obsidian_warehouse`）**虽是 git 仓库，但不纳入 JARVIS 的 git 文件回退**，靠 Obsidian 自带恢复兜底（2026-08-15 确认维持）

## Decisions so far

<!-- 一行一条已关闭票：足够判断相关性，点链接看详情 -->

- [01-模型接入验证](issues/01-model-compat.md) — tool calling ✅ 结构化输出 ✅；⚠️ workspace API 余额为 0，付费 deepseek-v4-flash 需充值；free 变体仅够冒烟
- [02-deepagents最新语法核验](issues/02-deepagents-syntax.md) — 最新 0.7.6；本机依赖需升级；设计文档 4 处需修正（CompositeBackend default=StateBackend 等）
- [04-researcher检索心智设计](issues/04-researcher-prompt.md) — researcher 定稿：固定导航式检索 + 搜索抓全文 + vault 优先融合 + 结构化带来源输出 + 双触发路由；⚠️ 发现 vault 已是 git 仓库（与「不纳入 git」决策冲突，待定）

## Not yet specified

- 定时检索的 cron 约定与 Obsidian Inbox 目录结构（二期，依赖一期 researcher 管道定型）
- 动态子代理 fan-out 是否可行（依赖模型写 JS 的能力验证）
- long-term memory `StoreBackend` 的 namespace 结构
- executor 的能力边界

## Out of scope

<!-- 已判定的范围外工作；关闭，永不转正 -->
