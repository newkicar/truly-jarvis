# CLAUDE.md

## 项目状态
- **一期 + 二期 + 三期 + TUI + 后续路线已实现**（Inbox 边界 / TUI 体验 / 测试质量，2026-08-19 收尾），代码在 `src/`，测试在 `tests/`（189 个单测全绿）。权威设计文档：`docs/specs/2026-08-15-javis-design.md`；路线 spec：`.scratch/javis-roadmap/spec.md`。
- 交付：`config.py`(.env 兼容解析+javis.json→Config)、`tools.py`(分层搜索)、`wiki.py`(wikilink/backlink)、`rag.py`(增量 RAG)、`subagents.py`(researcher + knowledge_keeper)、`agent.py`、`system_context.py`(get_system_context 工具)、`scheduler.py`、`time_travel.py`、`permissions.py`(HITL)、`vault_guard.py`+`inbox_snapshots.py`+`inbox_snapshot_middleware.py`(Inbox 写边界+快照)、`mcps.py`、`commands.py`(CLI+TUI 共用)、`streaming.py`(流式+HITL 决策+replay 快路径)、`tui_format.py`+`tui.py`(Textual TUI：流式 Markdown+权限 diff+`@`补全+侧边栏)、`path_completion.py`、`startup.py`、`main.py`(`--cli` 回退)、`smoke_test.py`(手动冒烟，`--tui` / `--tui-hitl` HITL 用例，不进 CI)、`tests/_manual/fanout_probe.py`；`skills/system-context/` 按需读取本机日期时间。
- 实现状态跟踪：`.scratch/javis-implementation/`、`.scratch/javis-tui/`、`.scratch/javis-roadmap/`（01–11 已关票）。

## 强制要求（README 约定，缺一不可）
1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。

## 关键技术决策（实现时容易跑偏）
- 主库 `deepagents`（`create_deep_agent`）；模型走 OpenAI 兼容端点 `https://opencode.ai/zen/go/v1`（go 按月套餐，已验证对话 + tool calling），模型 `mimo-v2.5`（2026-08-17 起，原 deepseek-v4-flash 因涨价弃用），模型名不加前缀，经 `.env` 的 `MODEL_ID` 读取。
- 交互形态：默认 TUI（Textual），`python -m src.main --cli` 回退纯 CLI。
- 知识库 = Obsidian vault（`E:\Thomas\Obsidian_warehouse`，路径可改，走 `javis.json`）。
  - 访问方式 = **WIKI 导航式**：`FilesystemBackend` 指向 vault，复用原生 `grep/glob/read_file`，加 `src/wiki.py` 的 wikilink/backlink 导航工具（出链/反链，**零索引**实时扫描）。
  - 语义增强 = **增量 RAG**（`src/rag.py`）：Ollama `bge-small-zh-v1.5` embedding + chromadb（索引存 `memory/rag-index/`），hash 增量索引只重建变更文件；`vault_semantic_search` 工具与 grep/wiki 结果合并去重。Ollama 不可用时自动回落。
- 记忆分离：知识 → Obsidian vault；信息记忆（偏好/行业）→ 项目 `memory/`。
  - 长期记忆用 FilesystemBackend 指向 `memory/`（文件持久、用户可看可编辑），**不用 StoreBackend**；`memory=` 注入所有 `*.md`（除 README）。
- 全局配置用 `javis.json`（模拟 opencode）；可变项放这里，不写死（含 `checkpoint_db`、`schedules_dir`）。**不含**用户所在地（用户可能在任意地点）。定时任务**外置**到 `schedules/*.json`（每任务一 JSON：时间/任务/保存路径/要求），增删 = 加删文件。
- **系统上下文**（ADR-0003）：日期/时间 + IP 推算城市，按需 `get_system_context` + `system-context` skill，**不**注入启动 system prompt；**不**读 user-profile 找所在地，**不**写死 `javis.json` location。
- **复用 deepagents 原生工具**（ls/read_file/write_file/edit_file/glob/grep/execute/task），不重造轮子。
- 架构：主代理 + 子代理（researcher / knowledge_keeper / executor）；研究类问题二期用动态子代理 fan-out。
- Time travel 双层：会话回退 = checkpointer（thread_id + checkpoint_id）；文件回退 = git 快照（仅项目目录，vault 不纳入 git），**手动 `/snapshot` 触发**（不用自动每轮 commit）。
- **CLI 展示约定**（`/history` 与 `/snapshots`）：只显示「边界点」（`/history` 过滤 source in input/fork/update，去掉 loop 超步骤噪音），从旧到新（最后=最新），每行带人类可读标签 + **短 id（checkpoint 前 13 位 / commit 前 10 位）**；`/replay` `/fork` `/rollback` 均支持短 id 前缀唯一匹配（歧义报错）。定时任务线程 `sched-*` 自动 `delete_thread` 清理，`/sessions` 也过滤，避免污染历史。
- **HITL 审批**（三期，对标 opencode permission）：主代理 `/workspace/` 路由用 `LocalShellBackend`（主代理+子代理直接有 `execute`，**不设独立 executor 子代理**）。`javis.json` 的 `permissions` 段控制 gated 工具（execute/write_file/edit_file/delete）：`allow`=自动放行、`ask`=每次审批（**默认**，不配置即审批）、`deny`=拒绝；支持对象规则集 `{"*": "ask", "git *": "allow"}`（最后匹配胜出）。实现：`src/permissions.py` 转成 `interrupt_on`（allow/deny 不中断），`deny` 由 `PermissionDenyMiddleware`（wrap/awrap_tool_call）在工具执行前拦截返回 error ToolMessage，middleware 与 `when` 谓词**共享同一 state 引用**并注入主代理+子代理；「always approve」只改 state + 写回 javis.json（**无需重建 agent**）。CLI 审批：`[y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮)`；TUI 改 Modal 四按钮（放行/永久放行/拒绝/编辑参数）。
- **MCP 工具**（三期）：`javis.json` 的 `mcps.servers` 段（OpenCode 风格）配置，即插即拔（编辑 → 重启生效，`enabled` 开关单个 server）。`type: "local"`(stdio，`command` 数组) / `"remote"`(streamable_http，`url`)，可选 `env`/`headers`/`cwd`。实现：`src/mcps.py` 的 `load_mcp_tools`（同步入口，启动时一次性加载，工具名带 server 前缀，如 `git_get_file`）；依赖 `langchain-mcp-adapters>=0.3.2`。**0.3.2 起每次工具调用自动开新 session，无长期生命周期**，只注入主代理（`create_deep_agent(tools=...)`），子代理不含 MCP 工具。单个 server 连接失败 → 跳过 + 警告，不影响启动。
- **TUI**（对标 opencode 终端界面）：`src/tui.py` 的 `JarvisApp`（Textual，`textual>=0.40.0`）。命令/会话纯逻辑在 `src/commands.py`（CLI+TUI 共用，`main.py` 只做装配与分支）。流式：`@work(thread=True)` 消费 `stream_events(v3)`，`call_from_thread` 逐字写 RichLog，`Esc` 取消（`get_current_worker().is_cancelled`）。消息样式：用户 secondary / AI primary 粗竖线带 `[b]JARVIS[/b]` 标题 + 末尾 `模型名 (耗时)`、工具 muted `✓/✗ 工具名(参数)`、子代理黄色。HITL 审批 = `PermissionModal`（ModalScreen）：接收 `ToolInvocation`（dataclass，name/path/args），`call_from_thread` 推模态 + `asyncio.Event` 等 dismiss，4 按钮 `放行(a)/永久放行(s)/拒绝(d)/编辑参数(e)`，编辑弹 `EditParamsModal`；resume 结构与 CLI `_handle_interrupts` 契约一致（`{"decisions": [...]}`，纯 dict 不包装 Command）。always-approve 持久化走 `commands.always_approve`（CLI+TUI 共享）。Header: title `JARVIS`，sub_title 显示 `thread_id + MCP:N`。主题持久化：`ctrl+t` 切换 Textual 主题（20 可选），`watch_theme` 写回 `javis.json` 的 `theme` 字段，启动时 `_restore_theme` 恢复。入口：`python -m src.main` 默认 TUI，`--cli` 回退。

## 环境与配置陷阱
- `.env` 当前是 `:` 分隔、小写键格式。`config.py` 的 `parse_env_text` 已兼容 `:` 与 `=` 两种分隔、键大小写不敏感；键名：`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`。`.env`、`checkpoints.sqlite` 已在 `.gitignore`。
- 环境：Windows，路径用 `pathlib` 或反斜杠。

## 分期
- ✅ 一期（已完成）：主代理 + researcher（指定检索）+ WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + javis.json + Tavily。
- ✅ 二期（已完成）：动态子代理 fan-out（CodeInterpreterMiddleware，实测通过）+ 定时检索（schedules/ 目录配置 + APScheduler + /reload-schedules 热重载）+ knowledge_keeper 知识沉淀 + git 文件回退（手动 /snapshot）+ 事件流式输出（stream_events v3）。单测 41 绿。
- 三期：executor（✅ 主代理直接 execute + HITL 审批）+ skill/mcp 接口（✅ skill 编写指南 + MCP 即插即拔 + 增量 RAG 增强（✅））。
- ✅ TUI（已完成，2026-08-18）：Textual 界面（commands.py 公共层 + 流式 + 权限 Modal + --tui/--cli 入口）。单测 165 绿。
- ✅ 后续路线（2026-08-19）：Inbox 边界 + 快照回退、TUI 体验（Markdown/diff/@/侧边栏）、测试与手动冒烟（`smoke_test --tui-hitl`）。

## Agent skills

### Issue tracker

本仓库的 issues 以 markdown 文件存于 `.scratch/<feature-slug>/`（本地 markdown，无 remote）。见 `docs/agents/issue-tracker.md`。

### Triage labels

五个规范角色，标签即名称：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：仓库根 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
