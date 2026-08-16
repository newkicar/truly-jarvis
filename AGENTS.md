# AGENTS.md

## 项目状态
- **一期 + 二期 MVP 已实现**（2026-08-15），代码在 `src/`，测试在 `tests/`（50 个单测全绿）。权威设计文档：`docs/specs/2026-08-15-javis-design.md`。
- 交付：`config.py`(.env 兼容解析+javis.json→Config)、`tools.py`(tavily_search)、`subagents.py`(researcher + knowledge_keeper)、`agent.py`(build_agent)、`scheduler.py`(APScheduler 定时检索)、`time_travel.py`(git 快照回退)、`permissions.py`(HITL 审批，对标 opencode permission)、`main.py`(CLI + /exit /sessions /history /replay /fork /snapshot /snapshots /rollback /reload-schedules + 审批 y/n/e/a)、`smoke_test.py`(真模型冒烟，手动)、`tests/_manual/fanout_probe.py`(fan-out 实测探针)。
- 实现状态跟踪：本地 issue tracker `.scratch/javis-implementation/`（spec + 票 01-15）。

## 强制要求（README 约定，缺一不可）
1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。

## 关键技术决策（实现时容易跑偏）
- 主库 `deepagents`（`create_deep_agent`）；模型走 OpenAI 兼容端点 `https://opencode.ai/zen/go/v1`（go 按月套餐，已验证对话 + tool calling），模型 `mimo-v2.5`（2026-08-17 起，原 deepseek-v4-flash 因涨价弃用），模型名不加前缀，经 `.env` 的 `MODEL_ID` 读取。
- 交互形态：纯 CLI。
- 知识库 = Obsidian vault（`E:\Thomas\Obsidian_warehouse`，路径可改，走 `javis.json`）。
  - 访问方式 = **WIKI 导航式**：`FilesystemBackend` 指向 vault，复用原生 `grep/glob/read_file`，**不要建 RAG/向量索引**。
- 记忆分离：知识 → Obsidian vault；信息记忆（偏好/行业）→ 项目 `memory/`。
  - 长期记忆用 FilesystemBackend 指向 `memory/`（文件持久、用户可看可编辑），**不用 StoreBackend**；`memory=` 注入所有 `*.md`（除 README）。
- 全局配置用 `javis.json`（模拟 opencode）；可变项放这里，不写死（含 `checkpoint_db`、`schedules_dir`）。定时任务**外置**到 `schedules/*.json`（每任务一 JSON：时间/任务/保存路径/要求），增删 = 加删文件。
- **复用 deepagents 原生工具**（ls/read_file/write_file/edit_file/glob/grep/execute/task），不重造轮子。
- 架构：主代理 + 子代理（researcher / knowledge_keeper / executor）；研究类问题二期用动态子代理 fan-out。
- Time travel 双层：会话回退 = checkpointer（thread_id + checkpoint_id）；文件回退 = git 快照（仅项目目录，vault 不纳入 git），**手动 `/snapshot` 触发**（不用自动每轮 commit）。
- **CLI 展示约定**（`/history` 与 `/snapshots`）：只显示「边界点」（`/history` 过滤 source in input/fork/update，去掉 loop 超步骤噪音），从旧到新（最后=最新），每行带人类可读标签 + **短 id（checkpoint 前 13 位 / commit 前 10 位）**；`/replay` `/fork` `/rollback` 均支持短 id 前缀唯一匹配（歧义报错）。定时任务线程 `sched-*` 自动 `delete_thread` 清理，`/sessions` 也过滤，避免污染历史。
- **HITL 审批**（三期，对标 opencode permission）：主代理 `/workspace/` 路由用 `LocalShellBackend`（主代理+子代理直接有 `execute`，**不设独立 executor 子代理**）。`javis.json` 的 `permissions` 段控制 gated 工具（execute/write_file/edit_file/delete）：`allow`=自动放行、`ask`=每次审批（**默认**，不配置即审批）、`deny`=拒绝；支持对象规则集 `{"*": "ask", "git *": "allow"}`（最后匹配胜出）。实现：`src/permissions.py` 转成 `interrupt_on`，`when` 谓词闭包引用可变 state，「always approve」只改 state + 写回 javis.json（**无需重建 agent**）。CLI 审批：`[y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮)`；三期 TUI 改选择式。

## 环境与配置陷阱
- `.env` 当前是 `:` 分隔、小写键格式。`config.py` 的 `parse_env_text` 已兼容 `:` 与 `=` 两种分隔、键大小写不敏感；键名：`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`。`.env`、`checkpoints.sqlite` 已在 `.gitignore`。
- 环境：Windows，路径用 `pathlib` 或反斜杠。

## 分期
- ✅ 一期（已完成）：主代理 + researcher（指定检索）+ WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + javis.json + Tavily。
- ✅ 二期（已完成）：动态子代理 fan-out（CodeInterpreterMiddleware，实测通过）+ 定时检索（schedules/ 目录配置 + APScheduler + /reload-schedules 热重载）+ knowledge_keeper 知识沉淀 + git 文件回退（手动 /snapshot）+ 事件流式输出（stream_events v3）。单测 41 绿。
- 三期：executor + skill/mcp 接口 + 增量 RAG 增强。

## Agent skills

### Issue tracker

本仓库的 issues 以 markdown 文件存于 `.scratch/<feature-slug>/`（本地 markdown，无 remote）。见 `docs/agents/issue-tracker.md`。

### Triage labels

五个规范角色，标签即名称：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：仓库根 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
