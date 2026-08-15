# CLAUDE.md

## 项目状态
- **一期 MVP 已实现**（2026-08-15），代码在 `src/`，测试在 `tests/`（16 个单测全绿）。权威设计文档：`docs/specs/2026-08-15-javis-design.md`。
- 一期交付：`config.py`(.env 兼容解析+javis.json→Config)、`tools.py`(tavily_search)、`subagents.py`(researcher)、`agent.py`(build_agent)、`main.py`(CLI + /exit /sessions /history /replay /fork)、`smoke_test.py`(真模型冒烟，手动)。
- 实现状态跟踪：本地 issue tracker `.scratch/javis-implementation/`（spec + 票 01-10）。

## 强制要求（README 约定，缺一不可）
1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。

## 关键技术决策（实现时容易跑偏）
- 主库 `deepagents`（`create_deep_agent`）；模型走 OpenAI 兼容端点 `https://opencode.ai/zen/go/v1`（go 按月套餐，已验证对话 + tool calling），模型 `deepseek-v4-flash`，模型名不加前缀。
- 交互形态：纯 CLI。
- 知识库 = Obsidian vault（`E:\Thomas\Obsidian_warehouse`，路径可改，走 `javis.json`）。
  - 访问方式 = **WIKI 导航式**：`FilesystemBackend` 指向 vault，复用原生 `grep/glob/read_file`，**不要建 RAG/向量索引**。
- 记忆分离：知识 → Obsidian vault；信息记忆（偏好/行业）→ 项目 `memory/`。
- 全局配置用 `javis.json`（模拟 opencode）；可变项放这里，不写死（含 `checkpoint_db`）。
- **复用 deepagents 原生工具**（ls/read_file/write_file/edit_file/glob/grep/execute/task），不重造轮子。
- 架构：主代理 + 子代理（researcher / knowledge_keeper / executor）；研究类问题二期用动态子代理 fan-out。
- Time travel 双层：会话回退 = checkpointer（thread_id + checkpoint_id）；文件回退 = git 快照（仅项目目录，vault 不纳入 git）。

## 环境与配置陷阱
- `.env` 当前是 `:` 分隔、小写键格式。`config.py` 的 `parse_env_text` 已兼容 `:` 与 `=` 两种分隔、键大小写不敏感；键名：`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`。`.env`、`checkpoints.sqlite` 已在 `.gitignore`。
- 环境：Windows，路径用 `pathlib` 或反斜杠。

## 分期
- ✅ 一期（已完成）：主代理 + researcher（指定检索）+ WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + javis.json + Tavily。
- 二期：动态子代理 fan-out + 定时检索（APScheduler）+ 长期记忆 StoreBackend + git 文件回退 + 事件流式输出（event streaming，票 11）。
- 三期：executor + skill/mcp 接口 + 增量 RAG 增强。

## Agent skills

### Issue tracker

本仓库的 issues 以 markdown 文件存于 `.scratch/<feature-slug>/`（本地 markdown，无 remote）。见 `docs/agents/issue-tracker.md`。

### Triage labels

五个规范角色，标签即名称：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：仓库根 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
