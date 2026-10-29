# Wayfinder Map：Jarvis 原生桌面 GUI 客户端

> 形态：local-markdown tracker（GitHub 网络不稳，恢复后迁 GitHub issues）
> 负责人：uida0712 · 创建：2026-10-26 · worktree：feat/gui-desktop @ D:/Python Project/truly-jarvis-gui（base: main @ 04089c9）

## Destination
可交接的**原生桌面 GUI spec**：Windows 优先、单机 exe、LLM 自配、无服务器；**整体迁移 TUI 全部能力**。
产物 = spec 草稿，足以支撑 to-spec → to-tickets → implement 开工。

## Decisions so far
- 2026-10-26 部署形态：单机客户端 exe，"谁下载谁使用"，不配服务器；LLM 各人自配（公司 OpenAI 兼容网关或第三方）。【用户定案】
- 2026-10-26 前端：不要 web，只做软件界面（原生 GUI）。架构学 opencode 解耦、视觉学 codex desktop 审批卡片、排除 deepseek 式纯聊天。【用户认可方向】
- 2026-10-26 范围：整体迁移 TUI 全部能力。【用户定案】
- 2026-10-26 工作方式：新建 git worktree（feat/gui-desktop）推进，主分支不动；暂不 push（GitHub 网络不稳，等用户信号）。【用户定案】
- 2026-10-26 T-001 框架选型：PySide6（Qt Widgets，不用 Addons）+ Nuitka 打包（onedir+签名，PyInstaller 备选）；中文 IME/Markdown 流式/拖选原生达标；Kivy/DearPyGui 因 IME 实证出局，Tkinter 能力不足；C#/Rust 宿主+Python 边界列 P2。详见 .scratch/research/T-001-framework-choice.md【研究代理】

- 2026-10-26 T-004 done：事件边界已解耦——streaming/commands/permissions/resilience 等既有模块零重构原样复用（无 Textual 依赖），GUI 仅新增 src/gui/（presenter + 第三 ask_action + 回合门 FIFO + 装配入口）；HITL resume 契约 {"decisions": [...]} 客户端无关；MVP 进程内跑 graph（A），独立 runtime worker（B）为升级路径。详见 .scratch/research/T-004-refactor-surface.md

- 2026-10-26 T-002 runtime/UI 解耦：照抄 opencode 事件三段式 {id,type,properties} + 首事件 server.connected + bootstrap replay；HITL 用 codex 式 server->client 反向请求（GUI 渲染 pending 审批卡，决策回写既有 langchain resume 契约，零改内核）；单机 exe 走 codex in-process bounded channel（协议 shape 预留 transport 可换）；审批 GUI = 卡片+表单+diff 三件套，永久放行 = opencode remember 语义（复用 commands.always_approve）。详见 .scratch/research/T-002-gui-decoupling.md【研究代理】
- 2026-10-26 T-003 LLM 自配：配置落用户全局 %APPDATA%\Jarvis\config.json（与安装目录分离，升级不覆盖，Chatbox 式损坏备份回退）；API key 走 Python keyring → Windows Credential Manager，config 只存 key_ref 不落明文（Continue 最高档先例）；端点探测抄 Jan GET {base}/models 五档状态 + 故障翻译表，取不到模型列表可手填 model id；首启 5 步向导可跳过；项目级 jarvis.json 只钉 model.provider。详见 .scratch/research/T-003-llm-config.md【研究代理】
- 2026-10-26 T-005 裁定（用户定案）：TUI 正常保留（开发者通道，行为不动）；GUI 为额外并行形态（给小白）；首发范围 = 整体迁移 TUI 全能力；单机 exe 谁下载谁使用、不配服务器、LLM 自配；遗留 (b) 小白默认值 / (c) Ollama+RAG+定时任务降级 / (d) GUI/TUI 并发 + SqliteSaver 锁 → spec 阶段裁定。详见 tickets/T-005-scope-grilling.md【用户裁定】

## Tickets（frontier）
| id | 标题 | label | assignee | status | blocked_by |
|---|---|---|---|---|---|
| T-001 | 原生 GUI 框架选型（Python/Windows） | wayfinder:research | uida0712（研究代理） | done | — |
| T-002 | agent 类项目 GUI 的 runtime/UI 解耦先例 | wayfinder:research | uida0712（研究代理） | done | — |
| T-003 | 桌面用户自配 LLM 端点/密钥先例 | wayfinder:research | uida0712（研究代理） | done | — |
| T-004 | 事件边界最小重构面（读本仓） | wayfinder:research | uida0712（研究代理） | done | — |
| T-005 | 整体迁移范围裁定与 TUI 共存策略 | wayfinder:grilling | 用户已裁定（HITL） | done | — |
| T-006 | GUI 骨架原型（聊天 + 审批卡片） | wayfinder:prototype | — | open（T-001/T-005 已定案，已解锁） | T-001, T-005 |

## Not yet specified（fog）
- 打包/签名/杀软误报策略 → 等 T-001
- 中文 IME/鼠标/拖选细节 → 等 T-001
- GUI/TUI 共存并发模型 + SqliteSaver 锁竞争 → 等 T-005
- UI 设计细节（视觉/布局/主题）→ 等 T-006 原型
- Ollama/RAG、定时任务作为可选依赖的降级策略 → 等 T-005
- GUI 测试策略（pytest-qt 等）→ 等 T-001

## Out of scope
- 服务器 + 浏览器形态（已排除：部署形态 = 单机客户端）
- web 前端（用户明确"不要 web，只做软件界面"）

## 红线 & 资源
- AGENTS.md 红线：① 动手实现前先搜 GitHub 找优秀开源项目参考，严禁闭门造车；② deepagents 更新快，先查官方文档确认最新版功能与语法。
- 引用 skills：research / grilling / domain-modeling / prototype。
- 先例池：codex（desktop/CLI/云）、opencode（serve+多客户端）、LM Studio、Chatbox、Jan、AnythingLLM、Continue/Roo Code、LangSmith managed deep agents（React useStream）。
- 研究代理产出：.scratch/research/T-00X-*.md；工单文件：.scratch/gui-wayfinder/tickets/。
