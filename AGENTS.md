# AGENTS.md

## 项目状态
- **一期 + 二期 + 三期 + TUI + 后续路线 + 泛化已实现**（项目根 / workspace-first @ / / 建议，2026-08-20 收尾），代码在 `src/`，测试在 `tests/`（202 个单测全绿）。权威设计文档：`docs/specs/2026-08-15-javis-design.md`；泛化 spec：`.scratch/javis-generalization/spec.md`。
- 交付：`config.py`(.env 兼容解析+jarvis.json→Config+`project_root`+`agents`)、`project_paths.py`(cwd 发现项目根+`~/.jarvis` 用户全局)、`skill_paths.py`(skill 三层发现)、`config_agents.py`(jarvis.json `agents` 段追加子代理)、`tools.py`(分层搜索)、`wiki.py`(wikilink/backlink)、`rag.py`(增量 RAG)、`subagents.py`(researcher + knowledge_keeper)、`agent.py`、`scheduler.py`、`time_travel.py`、`permissions.py`(HITL)、`vault_guard.py`+`inbox_snapshots.py`+`inbox_snapshot_middleware.py`(Inbox 写边界+快照)、`mcps.py`、`commands.py`(CLI+TUI 共用)、`streaming.py`(流式+HITL 决策+replay 快路径)、`tui_format.py`+`tui.py`(Textual TUI：流式 Markdown+权限 diff+`@`/`/`补全+侧边栏)、`path_completion.py`+`slash_completion.py`+`tui_completion.py`、`startup.py`、`main.py`(`--cli` 回退)、`smoke_test.py`(手动冒烟，`--tui` / `--tui-hitl` HITL 用例，不进 CI)、`tests/_manual/fanout_probe.py`。
- 实现状态跟踪：`.scratch/javis-implementation/`、`.scratch/javis-tui/`、`.scratch/javis-roadmap/`（01–11 已关票）、`.scratch/javis-generalization/`（01–07 已关票）。

## 强制要求（README 约定，缺一不可）
1. 动手实现前，先到 GitHub 搜索优秀开源项目参考。
2. deepagents 更新很快，先通过 langchain MCP（docs-langchain）确认最新版功能与语法再实现。

## 关键技术决策（实现时容易跑偏）
- 主库 `deepagents`（`create_deep_agent`）；模型走 OpenAI 兼容端点 `https://opencode.ai/zen/go/v1`（go 按月套餐，已验证对话 + tool calling），模型 `mimo-v2.5`（2026-08-17 起，原 deepseek-v4-flash 因涨价弃用），模型名不加前缀，经 `.env` 的 `MODEL_ID` 读取。
- 交互形态：默认 TUI（Textual），`python -m src.main --cli` 回退纯 CLI。
- **项目根**（ADR-0004）：`discover_project_root()` 从 cwd 向上找 `jarvis.json`；`/workspace/` = `Config.project_root`（非安装目录）；`JARVIS_PROJECT_ROOT` 可覆盖。新项目：`python -m src.main --init`。
- **路径放开**（#10，2026-08-25）：workspace backend 以 `virtual_mode=False` 构造——文件工具（ls/read/write/edit/glob/grep）接受**任意磁盘路径**（绝对路径按原样解析、相对路径以项目根为基准），`/workspace/ /vault/ /memories/ /skills/` 等虚拟前缀降级为快捷方式（CompositeBackend 路由仍优先匹配）。安全边界 = HITL permissions + vault 写保护 + shell 虚拟前缀拦截，不靠 backend 锁死路径（deepagents unrestricted 语义，对标 opencode external_directory 权限模型）。
- 知识库 = Obsidian vault（**可选**，路径写在 `jarvis.json` 的 `knowledge_base` 键——不同电脑可配不同路径，留空 `""` 或删除该键 = 无 `/vault/`；兼容旧键 `obsidian_vault`，`knowledge_base` 优先），路由 `/vault/`。
  - 访问方式 = **WIKI 导航式**：`FilesystemBackend` 指向 vault，复用原生 `grep/glob/read_file`，加 `src/wiki.py` 的 wikilink/backlink 导航工具（出链/反链，**零索引**实时扫描）。
  - 语义增强 = **增量 RAG**（`src/rag.py`）：Ollama `bge-small-zh-v1.5` embedding + chromadb（索引存 `memory/rag-index/`），hash 增量索引只重建变更文件；`vault_semantic_search` 工具与 grep/wiki 结果合并去重。Ollama 不可用时自动回落。
- 记忆分离：知识 → Obsidian vault；信息记忆（偏好/行业）→ 项目 `memory/`。
  - 长期记忆用 FilesystemBackend 指向 `memory/`（文件持久、用户可看可编辑），**不用 StoreBackend**；`memory=` 注入所有 `*.md`（除 README）。
- 全局配置用 `jarvis.json`（模拟 opencode）；可变项放这里，不写死（含 `checkpoint_db`、`schedules_dir`）。**不含**用户所在地（用户可能在任意地点）。定时任务**外置**到 `schedules/*.json`（每任务一 JSON：时间/任务/保存路径/要求），增删 = 加删文件。
- **系统上下文**（ADR-0003）：启动 prompt 仅注入**当天日期+星期**；精确时间/城市**只用 `execute`**（Get-Date、curl IP），**禁止** CodeInterpreter/eval；**不**读 user-profile 找所在地，**不**写死 `jarvis.json` location。
- **用户全局目录**：`~/.jarvis`（`JARVIS_HOME` 可改）存放全局 skill 与可写配置；安装目录只读随包默认 skill（`/builtin-skills/`）。
- **复用 deepagents 原生工具**（ls/read_file/write_file/edit_file/glob/grep/execute/task），不重造轮子。
- 架构：主代理 + 子代理（researcher / knowledge_keeper / executor）；研究类问题二期用动态子代理 fan-out。`jarvis.json` 的 `agents` 段可**追加**自定义子代理（`description` + `system_prompt`，可选 `permissions`），**不可**覆盖内置 researcher/knowledge_keeper，**不可**在 JSON 里开放任意 tools 列表。
- Time travel 双层：会话回退 = checkpointer（thread_id + checkpoint_id）；文件回退 = git 快照（仅项目目录，vault 不纳入 git），**手动 `/snapshot` 触发**（不用自动每轮 commit）。
- **CLI 展示约定**（`/history` 与 `/snapshots`）：只显示「边界点」（`/history` 过滤 source in input/fork/update，去掉 loop 超步骤噪音），从旧到新（最后=最新），每行带人类可读标签 + **短 id（checkpoint 前 13 位 / commit 前 10 位）**；`/replay` `/fork` `/rollback` 均支持短 id 前缀唯一匹配（歧义报错）。定时任务线程 `sched-*` 自动 `delete_thread` 清理，`/sessions` 也过滤，避免污染历史。
- **HITL 审批**（三期，对标 opencode permission）：主代理 `/workspace/` 路由用 `LocalShellBackend`（主代理+子代理直接有 `execute`，**不设独立 executor 子代理**）。`jarvis.json` 的 `permissions` 段控制 gated 工具（execute/write_file/edit_file/delete）：`allow`=自动放行、`ask`=每次审批（**默认**，不配置即审批）、`deny`=拒绝；支持对象规则集 `{"*": "ask", "git *": "allow"}`（最后匹配胜出）。实现：`src/permissions.py` 转成 `interrupt_on`（allow/deny 不中断），`deny` 由 `PermissionDenyMiddleware`（wrap/awrap_tool_call）在工具执行前拦截返回 error ToolMessage，middleware 与 `when` 谓词**共享同一 state 引用**并注入主代理+子代理；「always approve」只改 state + 写回 jarvis.json（**无需重建 agent**）。CLI 审批：`[y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve(q 放弃本轮)`；TUI 改 Modal 四按钮（放行/永久放行/拒绝/编辑参数）。
- **执行韧性**（`src/resilience.py`，2026-08-24，对标 codex/opencode harness）：错误分类决策表（retryable→指数退避±抖动重试，状态行可见；auth/context 超限不重试）；步数预算 `jarvis.json` `execution.max_steps`（默认 200，替代硬编码 recursion_limit=30），接近预算软着陆提醒（StepBudgetMiddleware，拼 system 不入历史）；doom-loop 防御（同名同参失败连续 3 次→工具结果附引导，成功清零）；ChatOpenAI max_retries=3+timeout；prompt 执行循环铁律（write_todos 分解→执行→核对→纠错→再执行；唯一停下条件=≥3 种方案仍失败→报告清单）。
- **执行韧性二期**（2026-08-25，教程 0001/0002/0005/0006 课落地，原则「提示词是建议，代码才是边界」）：①`ToolErrorBoundaryMiddleware`（resilience.py，主代理+子代理最外层）：任何工具异常→error ToolMessage+换方案引导，backend 层 ValueError 不再炸穿整轮；②`DoomLoopMiddleware` 两级处置：3 次软引导 / **5 次硬熔断**（wrap_tool_call 预检在执行前拦截，同名同参签名锁死至换参数；失败判定含 deepagents execute 的 `[Command failed with exit code N]` 状态行）；③`InheritedEnvShellBackend`（`src/shell_backend.py`，替代裸 LocalShellBackend）：deepagents 默认 `inherit_env=False` 子进程空 PATH（Windows 全命令不可用的事故根因），强制继承环境 + mbcs 解码容错 + **虚拟前缀守卫**（execute 收到 `/workspace/` 等前缀→执行前拦截并指路，前缀表来自 CompositeBackend 路由）；④`force_handoff`（commands.py+streaming.py）：步数上限 GraphRecursionError 时用 `_jarvis_model` 直调模型（不进 graph 不写历史）生成「已完成/未完成/下一步」结构化交接，无模型时回落原提示；⑤fatal 异常路径恢复 finalize_turn（修 400-repair 重构回归）；⑥对抗性 harness suffix（beast.txt 风格逐条打击已观察弱点：只说不做/不读报错/微调参数≠换方案/harness 熔断不许再发）；⑦**JARVIS.md 项目指令层**（`project_paths.load_project_instructions`）：`~/.jarvis/JARVIS.md`（全局）+ `{project_root}/JARVIS.md`（项目级）自动发现注入 system prompt（对标 AGENTS.md 分层，启动时读一次）。单测 339 绿。已知问题：bash 管道环境下长任务流式偶发静默 exit=1（原生层崩溃无 traceback，TUI 路径未复现，待查）。
- **MCP 工具**（三期）：`jarvis.json` 的 `mcps.servers` 段（OpenCode 风格）配置，即插即拔（编辑 → 重启生效，`enabled` 开关单个 server）。`type: "local"`(stdio，`command` 数组) / `"remote"`(streamable_http，`url`)，可选 `env`/`headers`/`cwd`。实现：`src/mcps.py` 的 `load_mcp_tools`（同步入口，启动时一次性加载，工具名带 server 前缀，如 `git_get_file`）；依赖 `langchain-mcp-adapters>=0.3.2`。**0.3.2 起每次工具调用自动开新 session，无长期生命周期**，只注入主代理（`create_deep_agent(tools=...)`），子代理不含 MCP 工具。单个 server 连接失败 → 跳过 + 警告，不影响启动。
- **TUI**（对标 opencode 终端界面）：`src/tui.py` 的 `JarvisApp`（Textual，`textual>=0.40.0`）。命令/会话纯逻辑在 `src/commands.py`（CLI+TUI 共用，`main.py` 只做装配与分支）。流式：`@work(thread=True)` 消费 `stream_events(v3)`，`call_from_thread` 逐字写 RichLog，`Esc` 取消（`get_current_worker().is_cancelled`）。消息样式：用户 secondary / AI primary 粗竖线带 `[b]JARVIS[/b]` 标题 + 末尾 `模型名 (耗时)`、工具 muted `✓/✗ 工具名(参数)`、子代理黄色。对话区 `CopyableRichLog` 维护纯文本缓冲；`jarvis.json` `tui.copy_on_select` 开启拖选松开即复制。HITL 审批 = `PermissionModal`（ModalScreen）：接收 `ToolInvocation`（dataclass，name/path/args），`call_from_thread` 推模态 + `asyncio.Event` 等 dismiss，4 按钮 `放行(a)/永久放行(s)/拒绝(d)/编辑参数(e)`，编辑弹 `EditParamsModal`；resume 结构与 CLI `_handle_interrupts` 契约一致（`{"decisions": [...]}`，纯 dict 不包装 Command）。always-approve 持久化走 `commands.always_approve`（CLI+TUI 共享）。Header: title `JARVIS`，sub_title 显示 `项目名 + thread_id + MCP:N`。`@` workspace 优先补全 + `/` 命令建议：**Tab** 接受，**Enter** 发送。主题持久化：`ctrl+t` 切换 Textual 主题（20 可选），`watch_theme` 写回 `jarvis.json` 的 `theme` 字段，启动时 `_restore_theme` 恢复。**粘贴**：`PasteInput` 子类（`src/tui.py`）覆盖默认 action_paste：ctrl+v / ctrl+shift+v / 右键(button=2) / 中键(button=3) 均走 OS 剪贴板读取（Windows `powershell Get-Clipboard -Raw` + UTF-8 防 GBK 乱码），解决 Textual app.clipboard 只含 app 内复制内容的限制。**侧边栏摘要**（#11，2026-08-25）：会话条目显示首条用户消息摘要（`commands.first_human_text` 截 18 字、空回落 thread_id），`/sessions` 输出同带摘要。**执行 spinner**（#09，2026-08-25）：流式期间输入框下方 braille 轮播（`tui_format.spinner_line`，80ms set_interval UI 线程驱动），`tui.animations=false` 静态 ⋯、`spinner_style="none"` 隐藏。入口：`python -m src.main` 默认 TUI，`--cli` 回退。
- **Plan/Act 双模式**（#08，2026-08-25，对标 opencode Tab 切换 build/plan）：模式存 `permission_state["mode"]`（与 deny middleware 共享同一 state 引用，切换零重建）；`src/plan_mode.py` 的 `PlanModeMiddleware` 注入主代理——Plan 模式下 wrap_tool_call 拦截 write_file/edit_file/delete（error ToolMessage 引导先规划）、wrap_model_call 往当轮 system 追加规划约束（不入历史）；TUI **Tab**（补全不活跃时）/ Shift+Tab 切换，绑定在 PasteInput（widget 级先于 Screen 的 focus_next），editor_frame `-plan` class 变 `$success` 边框（160ms transition），Header sub_title 尾部显示模式名，AI 回复头标注 `[Act]`/`[Plan]`。execute 不做命令级读写解析（靠提示词约束）。

## 环境与配置陷阱
- `.env` 当前是 `:` 分隔、小写键格式。`config.py` 的 `parse_env_text` 已兼容 `:` 与 `=` 两种分隔、键大小写不敏感；键名：`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`。`.env`、`checkpoints.sqlite` 已在 `.gitignore`。
- 环境：Windows，路径用 `pathlib` 或反斜杠。

## 分期
- ✅ 一期（已完成）：主代理 + researcher（指定检索）+ WIKI 导航知识库 + SqliteSaver 短期记忆 + 会话回退 + jarvis.json + Tavily。
- ✅ 二期（已完成）：动态子代理 fan-out（CodeInterpreterMiddleware，实测通过）+ 定时检索（schedules/ 目录配置 + APScheduler + /reload-schedules 热重载）+ knowledge_keeper 知识沉淀 + git 文件回退（手动 /snapshot）+ 事件流式输出（stream_events v3）。单测 41 绿。
- 三期：executor（✅ 主代理直接 execute + HITL 审批）+ skill/mcp 接口（✅ skill 编写指南 + MCP 即插即拔 + 增量 RAG 增强（✅））。
- ✅ TUI（已完成，2026-08-18）：Textual 界面（commands.py 公共层 + 流式 + 权限 Modal + --tui/--cli 入口）。单测 165 绿。
- ✅ 后续路线（2026-08-19）：Inbox 边界 + 快照回退、TUI 体验（Markdown/diff/@/侧边栏）、测试与手动冒烟（`smoke_test --tui-hitl`）。
- ✅ 泛化（2026-08-20）：项目根发现、workspace-first `@`、`/` 命令建议、Tab/Enter 非阻塞补全（ADR-0004）。

## Agent skills

### Issue tracker

本仓库的 issues 以 markdown 文件存于 `.scratch/<feature-slug>/`（本地 markdown，无 remote）。见 `docs/agents/issue-tracker.md`。

### Triage labels

五个规范角色，标签即名称：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：仓库根 `CONTEXT.md` + `docs/adr/`。见 `docs/agents/domain.md`。
