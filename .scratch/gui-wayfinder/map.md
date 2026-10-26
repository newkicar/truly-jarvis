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

## Tickets（frontier）
| id | 标题 | label | assignee | status | blocked_by |
|---|---|---|---|---|---|
| T-001 | 原生 GUI 框架选型（Python/Windows） | wayfinder:research | uida0712（研究代理） | open | — |
| T-002 | agent 类项目 GUI 的 runtime/UI 解耦先例 | wayfinder:research | uida0712（研究代理） | open | — |
| T-003 | 桌面用户自配 LLM 端点/密钥先例 | wayfinder:research | uida0712（研究代理） | open | — |
| T-004 | 事件边界最小重构面（读本仓） | wayfinder:research | uida0712（研究代理） | open | — |
| T-005 | 整体迁移范围裁定与 TUI 共存策略 | wayfinder:grilling | 待用户裁定（HITL） | open | — |
| T-006 | GUI 骨架原型（聊天 + 审批卡片） | wayfinder:prototype | — | open | T-001, T-005 |

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
