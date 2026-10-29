# T-002 研究：agent 类项目 GUI 的 runtime/UI 解耦先例

> 工单：`.scratch/gui-wayfinder/tickets/T-002-gui-decoupling.md` · 研究代理 · 2026-10-26
> 检索方式：2026-10-26 在线搜索（GitHub/官方文档，链接均已逐一打开验证）；少数仓库内细节未单独验证的条目标注**【离线推断、未验证】**。

## TL;DR

**所有先例收敛到同一形状：runtime 单实例 + UI 只是客户端 + 一套协议承载「事件流 / 会话线程 / 审批决策」三流。**

1. **事件协议**：照抄 opencode server 的三段式 `{id, type, properties}` + 首事件连接标记（`server.connected`）+ 断线 bootstrap replay 重建初态；HITL 审批照抄 codex 的「server→client 反向请求」形状（GUI 渲染 pending-approval 对象，决策经回写通道进 runtime），决策 payload 仍走 Jarvis 既有 langchain `resume {"decisions":[...]}` 契约（permissions.py edit 决策已全工具开放，零改内核）。
2. **会话/线程**：照抄 opencode 的 thread CRUD + 全量状态批量接口 + fork/abort/diff/revert；thread_id 打标每个事件，checkpointer（SqliteSaver）是唯一真相源，UI 侧 bootstrap replay 恢复；`sched-*` 线程协议层过滤。
3. **审批"编辑参数" GUI 表达**：三件套 = **卡片（审批卡）+ 表单（参数编辑框）+ diff（文件类预览）**。execute→命令预览卡+单行编辑框（Windows 多行已被 shell_backend 预拦截，编辑框单行即可）；write/edit→diff 预览 + 参数表单；delete→确认卡；"永久放行"= opencode `remember` 语义（Jarvis 已有 `commands.always_approve`/前缀规则，复用零改内核）。
4. **单机 exe 落地**：照抄 codex app-server 的 **in-process bounded channel** 先例——同一协议三种 transport（stdio / WebSocket / in-process），本期 exe 走 in-process（UI 线程与 runtime 线程直接对话，免进程边界），协议 shape 预留 transport 可换，未来 `--serve` 多客户端形态只需加 transport 不改协议。

---

## 先例清单（带链接 + 可照抄要点）

### ① opencode —— serve + 多客户端事件协议（首要照抄对象）

- 文档：https://opencode.ai/docs/server/ · 仓库：https://github.com/anomalyco/opencode
- 怎么做：`opencode serve` 起无头 HTTP server（默认 127.0.0.1:4096），`/doc` 端点直接出 **OpenAPI 3.1 → 生成 JS SDK**；**TUI 本身就是该 server 的一个客户端**（多个客户端、IDE 插件、`/tui` 端点驱动 TUI 并存）。
- 可照抄的协议要点：
  - **事件三段式**：SSE `GET /global/event`（全局）/ `GET /event`（per-session），**首事件 `server.connected` 作连接标记**；每个事件 `{id, type, properties}`。事件类型集（GitHub 实证，`packages/sdk/js/src/v2/gen/types.gen.ts`）：`message.updated` / `message.removed` / `message.part.updated` / `message.part.removed` / `message.part.delta`（token 增量）/ `session.status` / `session.diff` / `todo.updated` / `permission.asked` / `permission.replied`，另有带 `seq` 的 `sync` event-sourcing 变体。
  - **会话 API**：`GET /session`（列表）、`POST /session {parentID, title}`（子会话=子代理上下文）、`GET /session/status`（**全部会话状态一次批量返回**）、`fork` / `abort` / `diff` / `revert` / `unrevert`；发信双通道 `POST /session/:id/message`（同步等完）与 `prompt_async`（204 不等完）。
  - **HITL**：`POST /session/:id/permissions/:permissionID` body `{response, remember?}`——**`remember` = "always approve" 语义**，对应 Jarvis 的 always-approve / 命令前缀放行。
  - **断线不丢**：客户端 reducer（`packages/app/src/context/global-sync/event-reducer.ts`，事件→本地 store）+ **bootstrap replay**（`packages/opencode/src/cli/cmd/run/session-replay.ts`：`bootstrap:message:*` 事件重放重建初态）。
  - **审批卡带参数 schema 先例**：`subagent-data.ts` 中 tool call 参数随 `call` part 传给 permission view。
  - 协议由 OpenAPI 生成 typed client = 两端（server runtime / UI 客户端）契约强类型，UI 侧不用手写 wire 解析。

### ② codex —— desktop/CLI/云共享 runtime + 审批反向请求

- 仓库：https://github.com/openai/codex（核心 `codex-rs/app-server`，协议 crate `codex-app-server-protocol`）
- 怎么做：**同一 JSON-RPC 协议三种 transport**：stdio / WebSocket（TCP+Unix，桌面与远程）/ **in-process bounded channel**（`codex-rs/app-server/src/in_process.rs`："replaces socket/stdio transports with bounded in-memory channels... preserving app-server semantics"，背压 = try_send → WouldBlock）。**单机 exe 同进程客户端免进程边界的直接先例**。
  - 共享 daemon：`codex-rs/app-server-daemon`（PID file + lock 管生命周期）；`codex agents` 子命令 = 浏览共享本地 daemon 上所有 agent 会话；`codex remote-control` + 配对码（远程桌面即"多客户端"）。
  - **事件**：`ThreadItem` tagged enum（`v2/item.rs`：UserMessage / AgentMessage / Reasoning / FunctionCallOutput / Plan / DynamicToolCall…）；**live 通知与 `thread/read` 历史重建共用同一 builder**（`item_builders.rs` 注释"sharing the logic avoids drift"）；`ThreadRollbackResponse`（per-thread 回滚，同 Jarvis `/rollback` 形状）。
  - **HITL = server→client 反向请求**：`ExecApprovalRequest` / `PermissionsApprovalRequest` / `ApplyPatchApprovalRequest` / `McpElicitation`（`tui/src/bottom_pane/approval_overlay.rs`）；TUI 用 `InterruptManager` **FIFO 排队、一次只显一个**（`chatwidget/interrupts.rs`）；apply_patch 审批 = **diff**（`EditApprovalRequested {cwd, changes: Vec<PathBuf>}`），exec 审批 = 命令预览。

### ③ LM Studio / Jan / ChatBox —— 本地 runtime + GUI 客户端（单机形态先例）

- LM Studio：闭源产品，官方 server 文档 https://lmstudio.ai/docs/developer/core/server （本地推理 server，端口 12345，**OpenAI 兼容 REST + SSE 流式**；GUI 内嵌 server，外部客户端连同一 server）；bug tracker https://github.com/lmstudio-ai/lmstudio-bug-tracker 。可抄点：「GUI 宿主 + 本地 server 同机」单机分层、SSE 流式契约。
- Jan：https://github.com/janhq/jan （AGPL；Electron→Tauri 迁移）：桌面壳 + 内嵌本地推理 runtime（llama.cpp），模块化、file-based 持久化；架构页 https://jan.ai/developer/architecture （官方标注 "under construction scratchpad"）；独立 server 仓库 https://github.com/janhq/server 。可抄点：「runtime 可独立 server 化但默认内嵌」的可演进路径。
- ChatBox：https://github.com/chatboxai/chatbox （Electron，GPL-3.0）：**用户自配 LLM 端点/密钥（OpenAI 兼容）设置页**——与 Jarvis「LLM 各人自配」同构（另见 T-003 工单）。可抄点：自配端点的设置模型。

### ④ Continue / Roo Code —— IDE 扩展作为 agent 客户端

- Continue：https://github.com/continuedev/continue （被 Cursor 收购；VS Code / JetBrains / CLI 多 surface 共享同一 core）。
- Roo Code：https://github.com/RooCode-inc/Roo-Code 【链接未逐一在线验证，离线推断、未验证】
- 怎么做：事件通道 = 扩展 host ↔ webview **postMessage**；HITL/文件审批 = **diff 预览 + accept/reject** 是 IDE 圈标准表达【diff-approval 细节为离线推断，未验证】。可抄点：「审批 = diff 预览」的 GUI 表达；多 surface 共享 core 的解耦验证（CLI/IDE 都是 core 的客户端）。

### ⑤ LangSmith managed deep agents 官方 React useStream 模式

- 文档：https://docs.langchain.com/langsmith/javascript/managed-deep-agents-custom-frontend （官方 JS SDK）
- 怎么做：`useStream`（`@langchain/react`/`vue`/`svelte`/`angular` 四套）暴露 `stream.messages / toolProgress / interrupts / thread` 响应式值 + `stream.submit()`；**HITL 循环** = 检测 `stream.interrupted` → 读 `stream.interrupts` payload → `submit(Command(resume=...))`（与 https://docs.langchain.com/oss/javascript/langgraph/interrupts 的 `stream_events(v3)` 循环同构，即 Jarvis `streaming.py` 现状的 TS 镜像）。
- `toolProgress` 卡片模型（name / state / toolCallId / input / data / result / error，文档 https://docs.langchain.com/oss/javascript/langgraph/streaming ）。自定义事件通道 `onCustomEvent` + 服务端 `ui.push()`（generative-ui 文档）=「审批卡数据可走自定义事件通道」先例。可抄点：**UI 层把 interrupts 当作一等响应式状态**（不是轮询），resume 用 `Command(resume=...)` 语义。

---

## 可照抄的协议要点（三关注点逐条）

### 1. 事件协议形状（stream 事件 + HITL 审批跨层转递）

| 要点 | 先例出处 | 形状 |
|---|---|---|
| 事件三段式 | opencode `/event` SSE | `{id, type, properties}`，type 为点分层（`message.part.delta`） |
| 连接标记 | opencode 首事件 | `server.connected`，客户端据此触发 bootstrap replay |
| token 增量 | opencode `message.part.delta` / LangSmith `stream.messages` | 增量 delta 事件，UI 追加渲染不全量重绘 |
| 工具/子代理/TODO | opencode `message.part.updated`（call part 携带 tool 参数 schema）/ `todo.updated` | part 级状态事件，UI 卡片化（= LangSmith `toolProgress` 卡片模型） |
| HITL 审批跨层 | codex `ExecApprovalRequest` 等 server→client 反向请求；opencode `permission.asked` + `POST /permissions/:id {response, remember?}` | **审批是一个 pending 对象**（工具名+参数+会话 id），UI 渲染卡片，决策经专用通道回写；`remember` 字段承载「永久放行」 |
| 审批排队 | codex `InterruptManager` FIFO、一次显一个 | 多 interrupt 并发时 UI 层 FIFO 队列（Jarvis 已有 tui-ux7 thread 级 turn-gate，语义同构） |
| 断线不丢 | opencode session-replay `bootstrap:message:*` | UI 重连/启动时拉全量历史事件重放，再切 live |

### 2. 会话/线程管理模型（多会话并发、切换、恢复）

| 要点 | 先例出处 | 形状 |
|---|---|---|
| thread CRUD | opencode `GET/POST /session` | 列表 + 创建（`parentID` 支持子会话/子代理） |
| 全量状态批量 | opencode `GET /session/status` | 一次返回所有会话状态 → 侧边栏（Jarvis TUI 侧边栏摘要先例） |
| 并发/切换 | codex app-server daemon + `codex agents` 浏览全部会话；LM Studio GUI↔同机 server | runtime 单实例，会话是 runtime 内一等对象，UI 切换 = 换订阅的 thread，**不重建 runtime** |
| 中止 | opencode `abort` | 会话级 abort（对应 Jarvis tui-ux6 `request_drain` 语义） |
| 恢复 | opencode bootstrap replay + LangSmith `stream.thread` | 恢复 = 从持久层（checkpoint）重放事件重建 UI 状态，**UI 本地 store 可丢，真相源在 runtime** |
| 回滚/fork | opencode `diff/revert/unrevert/fork`；codex `ThreadRollbackResponse` | per-thread 历史操作 = Jarvis `/history /replay /fork /rollback` 的 API 化 |

### 3. 审批"编辑参数"的 GUI 表达（卡片 / 表单 / diff）

| 工具类型 | 先例 | GUI 表达 |
|---|---|---|
| execute | codex `ExecApprovalRequest` 命令预览 + 排队卡片 | 审批卡 = 命令预览（只读高亮）+ 单行编辑框（Windows 多行命令已被 shell_backend 预拦截，编辑框限制单行符合既有边界） |
| write_file / edit_file | codex `ApplyPatchApprovalRequest` = diff；Continue/Roo diff 预览【离线推断、未验证】 | 审批卡 = **diff 预览**（write 全量 / edit unified diff）+ 参数表单（路径可改） |
| delete | codex 反向请求确认卡 | 极简确认卡（路径 + 后果说明） |
| 编辑参数回传 | Jarvis TUI EditParamsModal（TUI 经验十/十一已实现「看得见改 + 多行」） | GUI 表单直接复用同契约：decision 形状 `{"decisions":[{type:"edit", args:...}]}` 回写 resume |
| 永久放行 | opencode `remember?`；codex PermissionsApprovalRequest 的持久化选项 | 卡片上「永久放行」按钮 = Jarvis `commands.always_approve` / `approve_prefix` 前缀规则回写 jarvis.json，GUI 只是渲染入口 |

---

## 对 Jarvis 的三层解耦建议（挂靠既有机制，不另起炉灶）

### L1 事件层：在 `streaming.py` 之上加「协议投影」

- 现状：TUI `@work(thread=True)` 消费 `stream_events(v3)` + HITL 决策 + replay 快路径，事件语义已齐。
- 建议：把 v3 事件**投影**为 opencode 式三段式 `{id, type, properties}` 线协议（事件类型命名对齐 `message.part.delta` / `message.part.updated` / `session.status` / `permission.asked` 等，加首事件 `server.connected`）。TUI 与 GUI 都消费投影后的事件，不再直连 `stream_events` 原始形态；`streaming.py` 内核（韧性四期熔断、SanitizeHistory、finalize_turn）零改动。
- HITL 转递：`permission.asked` 事件携带 pending-approval 对象（tool 名/参数/thread_id），GUI 渲染卡片后决策经回写通道（codex 式 server→client 反向请求形状）进 `{"decisions":[...]}` resume 契约——**permissions.py 的 approve/reject/edit 三决策与 tui-ux11 全工具 edit 开放零改内核**。
- 传输：本期单机 exe = **codex in-process bounded channel 先例**（UI 线程 ↔ runtime 线程内存通道，带 try_send 背压），协议 shape 保留 transport 可换（stdio/WebSocket = 未来 `--serve` P2）。

### L2 会话层：thread_id 打标 + checkpointer 真相源

- 每个事件带 `thread_id`；runtime 侧 thread CRUD/批量状态/diff/abort/rollback 镜像 opencode session API（落到 `commands.py` 既有 `/sessions /history /replay /fork /rollback /undo`，协议化不改逻辑）。
- 恢复：SqliteSaver 为唯一真相源；UI 本地 store 可随时重建（bootstrap replay = 拉该 thread 事件重放，复用 `streaming.py` replay 快路径）。
- `sched-*` 线程：协议层过滤（沿用 CLI 展示约定：`/sessions` 隐藏、自动 delete_thread）。
- 并发：runtime 单实例 + thread 级 turn-gate（tui-ux7 既有 FIFO 门直接升格为协议语义：abort/审批/新消息在门内排队），GUI 多会话切换 = 换订阅 thread 不重建 runtime。

### L3 审批 GUI 表达：卡片 + 表单 + diff 三件套

- 审批卡（`permission.asked` 渲染）：按工具分型——execute=命令预览卡+单行编辑框；write/edit=diff 预览+参数表单；delete=确认卡。排队 = FIFO 一次一个（codex InterruptManager / tui-ux7 turn-gate 同构）。
- 编辑参数：表单组件直接对齐 TUI 经验十「看得见改（只读原值展示 + 多行编辑框）」的交互语义，提交形状 = langchain `edit` 决策（tool_call id 保留、args 改写；1.3.x/1.4.x 双存储形式兼容见 tui-ux12 测试经验）。
- 永久放行：卡片按钮回写 `commands.always_approve` / 前缀规则（opencode `remember` 语义），YOLO 线程级免审批（tui-ux12）在 GUI 同样生效（Header 状态位 `[YOLO]` 镜像）。

### 不照抄 / 降优先级

- opencode `POST /message` 同步阻塞通道：不照抄（GUI 一律 async + 事件流）。
- `--serve` 多客户端 / remote-control 配对码：协议预留 transport 即可，形态列 P2（与 map.md Out of scope「无服务器」一致）。
- LangSmith `ui.push()` generative UI：本期不做自定义事件 UI 推送，`onCustomEvent` 通道列 P2。

---

## 风险与未决

1. **SqliteSaver 双客户端锁竞争**：TUI + GUI 同机并发写同一 checkpoint db（tui-ux7 已定位过「同 thread 双 graph 并发→SqliteSaver 锁竞争」根因）。建议：单 app 内 TUI/GUI 共享同一 runtime 实例与 checkpointer（同进程），不各开连接；跨进程多客户端形态（P2）需要单写者 + 读多写少隔离。**裁定权在 T-005（GUI/TUI 共存策略）**。
2. **useStream 无 PySide6 等价物**：官方 `useStream` 四套全是 web 框架绑定；PySide6 需自写薄响应层（信号槽 + 事件 reducer，形状参考 opencode event-reducer.ts + bootstrap replay），约 200~400 行量级【离线推断、未验证：无官方 Python desktop binding 先例】。
3. **codex 仓库内细节引用**（in_process.rs 背压语义、item_builders 共用 builder）为 2026-10-26 在线核实，codex 迭代快，实施前需 re-verify。
4. **Roo Code 仓库与 diff-approval 细节**未在线验证【离线推断、未验证】，仅 Continue 验证过；IDE 圈「审批=diff 预览」判断有 codex apply_patch diff 先例兜底。
5. **协议命名 vs Jarvis 既有词汇**：opencode 用 session/part/permission，Jarvis 用 thread/message/ToolInvocation——投影层需一张映射表（建议随 T-004「事件边界最小重构面」一并定稿，避免协议与最小重构面两次定案打架）。
6. **审批"编辑参数"对 execute 的编辑框单行限制**依赖 Windows 多行预拦截（resilience 四期 L1）：若未来放开 POSIX/多行语义，GUI 编辑框需升级为多行（TUI 经验十 ModalTextArea 方案可平移）。
