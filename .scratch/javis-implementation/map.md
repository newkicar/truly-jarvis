# Map: JARVIS 实现路径

`Type: map`  `Status: open`

## Destination

把 JARVIS 从设计文档（`docs/specs/2026-08-15-javis-design.md`）走到可运行的实现，并分阶段推进：一期（主代理 + researcher 指定检索 + WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + javis.json + Tavily）→ 二期（动态子代理 fan-out + 定时检索 + 长期记忆 + git 文件回退 + 事件流式输出）→ 三期（executor + skill/mcp 接口 + 增量 RAG）。**一二三期主体已实现（2026-08-18 收尾）**。

## Notes

- 领域：Python + deepagents 0.7.x + langchain-openai（base_url `https://opencode.ai/zen/go/v1`，模型 `mimo-v2.5`（2026-08-17 起替换 deepseek-v4-flash），go 按月套餐已验证可用）
- 环境：Windows；conda env `thomas`（Python 3.12.9，`D:/AIPrograms/Annaconda/envs/thomas/python.exe`）；pip + requirements.txt；一期 git init
- 每个会话前必读：`AGENTS.md`、`docs/specs/2026-08-15-javis-design.md`、`docs/agents/*.md`
- 强制要求：实现前到 GitHub 找参考；用 docs-langchain MCP 核对 deepagents 最新语法
- 本 map 只产出决策与事实，不产出交付物（除非票面 Notes 另行说明）
- 范围确认：vault（`E:\Thomas\Obsidian_warehouse`）**虽是 git 仓库，但不纳入 JARVIS 的 git 文件回退**，靠 Obsidian 自带恢复兜底（2026-08-15 确认维持）

## Decisions so far

<!-- 一行一条已关闭票：足够判断相关性，点链接看详情 -->

- [01-模型接入验证](issues/01-model-compat.md) — tool calling ✅ 结构化输出 ✅；⚠️ workspace API 余额为 0，付费 deepseek-v4-flash 需充值；free 变体仅够冒烟。**2026-08-17 起模型切换为 mimo-v2.5（deepseek 涨价弃用）**
- [02-deepagents最新语法核验](issues/02-deepagents-syntax.md) — 最新 0.7.6；本机依赖需升级；设计文档 4 处需修正（CompositeBackend default=StateBackend 等）
- [03-项目骨架搭建](issues/03-project-scaffold.md) — 已 git init + requirements + src/ 布局 + javis.json；依赖装好、冒烟通过；要点：SqliteSaver.from_conn_string 是 context manager
- [04-researcher检索心智设计](issues/04-researcher-prompt.md) — researcher 定稿：固定导航式检索 + 搜索抓全文 + vault 优先融合 + 结构化带来源输出 + 双触发路由；⚠️ 发现 vault 已是 git 仓库（与「不纳入 git」决策冲突，待定）
- [05-配置层](issues/05-config-layer.md) — `.env` 兼容 `:`/`=` 两种分隔、键名大小写不敏感；`javis.json` → Config dataclass，路径绝对化；缺关键配置明确报错
- [06-Tavily 搜索工具](issues/06-tavily-tool.md) — `tavily_search` 返回 URL 列表 + httpx 抓全文转 markdown + 结构化带来源输出；异常不崩溃
- [07-主代理组装](issues/07-main-agent.md) — `build_agent` 用 `create_deep_agent`；`CompositeBackend(default=StateBackend(), routes={/workspace/, /vault/, /memories/})`；SqliteSaver 需在 `with` 内创建
- [08-CLI 会话](issues/08-cli-session.md) — `input()` 交互循环；thread_id=session_id；重启上下文仍在（SqliteSaver 持久化）
- [09-会话回退](issues/09-session-time-travel.md) — `/sessions` `/history` `/replay` `/fork` 全部实现（invoke(None, prior.config) / update_state 分叉保留原历史）
- [10-真模型冒烟](issues/10-smoke-test.md) — `smoke_test.py` 手动触发，不进 CI；真实环境端到端通过
- [11-事件流式输出](issues/11-event-streaming.md) — 二期；已核实 deepagents 0.7.6 支持 `stream_events(version="v3")` typed-projection；子代理/工具调用/最终回答实时可见；顺带修 tavily search 缺 timeout
- [12-git 文件回退](issues/12-git-rollback.md) — `/snapshot` 手动触发：`git add -A` + commit `javis <checkpoint_id>` + 映射写 `git_mapping.sqlite`；`/rollback <short-cid>` 前缀匹配；vault 不纳入 git
- [13-定时检索](issues/13-scheduled-retrieval.md) — schedules/ 目录每任务一 JSON（时间/任务/保存路径/要求）；APScheduler + `/reload-schedules` 热重载；`sched-*` 线程自动 delete_thread 清理
- [14-knowledge_keeper](issues/14-knowledge-keeper.md) — 轻量子代理；**只新增、限写 `/vault/Inbox/`** 暂存区，绝不修改/删除既有笔记；wikilink 仅关联确实存在的笔记
- [15-动态子代理 fan-out](issues/15-fanout.md) — CodeInterpreterMiddleware 接入主代理（`subagents=True`），先实测消息序列 human→ai→tool×6→ai 通过
- **三期补充**（2026-08-18，未单列票，见 AGENTS.md 交付清单）：HITL 审批（permissions.py，allow/ask/deny + PermissionDenyMiddleware 拦截）+ MCP 工具（mcps.py，`mcps.servers` OpenCode 风格即插即拔）+ skill 编写指南（skills/README.md）+ 增量 RAG（rag.py）——均已实现并测试通过（94 单测全绿）

## Not yet specified

- 定时检索的 cron 约定已定型为 schedules/*.json（每任务一 JSON），vault 回写目录待用户确认 Inbox 归档流程
- long-term memory `StoreBackend` 的 namespace 结构（已决策改用 FilesystemBackend 指向 `memory/`，**不用 StoreBackend**）
- 三期已收尾（executor 定为主代理直接 execute，不再设独立 executor 子代理；skill/mcp 接口已实现）；后续待办：vault 回退增强（可选）

## Out of scope

<!-- 已判定的范围外工作；关闭，永不转正 -->
