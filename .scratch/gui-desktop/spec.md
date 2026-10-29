# GUI 原生桌面客户端 · Spec（一期：整体迁移 TUI 全能力）

> 状态：ready-for-agent · 2026-10-26 · worktree `feat/gui-desktop`
> 上游材料：`.scratch/gui-wayfinder/`（map + T-001~T-006 + 综合报告 report-2026-10-26.md）+ T-006 原型过稿（`.scratch/prototype/`）
> 本 spec 裁定报告遗留 b/c/d 三项 + 原型过稿全部反馈 + 记忆目录需求 + TUI 端三已知问题（GUI 对标实现）。

## Problem Statement

Jarvis 当前只有 TUI（终端）形态，无编程基础的同事（小白）无法使用：终端操作、斜杠命令、审批键盘流对他们门槛太高。需要一个**原生桌面 GUI 客户端**：单机 exe、谁下载谁使用（不配服务器）、LLM 各人自配（公司 OpenAI 兼容网关或第三方端点），能力与 TUI 全面对齐（首发即整体迁移，不做缩水版）。同时 TUI 正常保留，作为有代码基础用户的开发者通道，两者并行。

## Solution

- **形态**：Windows 优先的单机桌面 exe（Nuitka onedir + Inno Setup 安装包 + 代码签名），双击即用；LLM 端点/密钥首启向导配置（可跳过），配置存 `%APPDATA%\Jarvis\config.json`（与安装目录分离，升级不覆盖），密钥进 Windows Credential Manager（不落明文）。
- **架构**（T-002/T-004 定案）：GUI 是「第三个客户端」——既有 `src/` 逻辑层（streaming/commands/permissions/resilience 等）零行为改动复用；新增 `src/gui/` 薄响应层（presenter 事件泵 + 第三 ask_action + 回合门 FIFO + 装配入口），进程内跑 graph（架构 A），独立 runtime worker 进程（架构 B）为升级路径，不推倒重来。
- **UI**：PySide6（仅 QtWidgets，禁 Addons/WebEngine；pip 元包会连带装 Addons+WebEngine，依赖应钉 **PySide6-Essentials**——原型实证项），聊天流 + codex 式内联审批卡片（卡片+表单+diff 三件套）+ 会话侧栏 + 图片附件条；TUI 经验整体平移（粘底/排队/撤回/双模式/免审批）。
- **小白友好默认值**（遗留 b 裁定）：审批卡片按钮醒目（放行为主按钮默认焦点，平移 tui-ux8 实证）；工具调用行默认折叠为一行 +「＋ 详情」展开（codex 对标）；斜杠命令面板收纳进「命令」菜单（不占主界面）；YOLO/Plan 等高级模式入口保留但默认 Act 模式。
- **可选依赖降级**（遗留 c 裁定）：RAG（chromadb/onnxruntime 100MB+ 原生大包）不入基础 exe，缺失自动回落 grep/wiki 检索（AGENTS 既有语义），需要时引导装 wheel 或外部 Ollama；定时任务 = 可选模块，GUI 未启用时不启动 scheduler。
- **同机 GUI/TUI 并发**（遗留 d 裁定）：同 app 内共享单 runtime 实例与 checkpointer（进程内）；后启动者检测到 runtime 已存在则**不 start scheduler**、JumpIn 只在本进程生效；checkpoint db 加 `busy_timeout`/WAL pragma；跨进程多客户端 = P2 单写者模型（本期不做）。
- **记忆目录（用户全局化，跨项目）**：信息记忆（用户偏好/复盘 `agent-memory.md`）从项目 `memory/` 迁移到 `%USER%\.jarvis`（`JARVIS_HOME` 可改），跨项目复用；项目 `memory/` 仅保留项目信息记忆；`/memories/` 路由与 `memory=` 注入清单随主线版本对齐（主线正在改，GUI 侧不重复实现，spec 前 rebase 同步）。
- **TUI 端三已知问题（用户将同步报 TUI 线）——GUI 直接按对标实现，不复制 TUI bug**：
  1. 代理思考内容不上屏 → GUI 渲染思考块（字号小、颜色淡、与正文区分）；思考通道若落在共享流层（streaming 回调），属两端公共 seam，TUI 同改。
  2. 切对话再回来工具调用记录消失 → GUI 会话回放含完整工具记录（从检查点消息重建，重启后亦然）。
  3. 工具调用无展开细节 → GUI 工具行「＋ 详情」展开（codex「+ Show details」/ opencode「Click to expand」对标）。

## User Stories

1. As a 小白用户, I want 双击安装后的 exe 就能看到 Jarvis 聊天界面, so that 我不需要终端/命令行基础就能用.
2. As a 小白用户, I want 首次启动时有 5 步向导配 LLM（选网关→填地址密钥→测试连接→选模型，可跳过）, so that 公司网关/第三方端点都能接、不会配错.
3. As a 小白用户, I want 密钥存在系统凭据管理器里而不是配置文件中, so that 配置被拷走也不会泄露密钥、域账号重置时向导引导我重配而不是崩.
4. As a 小白用户, I want 保存 LLM 配置时自动探测连接（五档状态：成功/密钥无效/无权限/限流/连不上，各配人话文案）, so that 我能看懂失败原因而不用猜.
5. As a 用户, I want 内网网关没实现模型列表接口时也能手填模型名保存成功, so that 我不用被「拉不到列表」卡死.
6. As a 用户, I want 流式回答逐字出现在对话区、Markdown 渲染（代码块/列表/表格）, so that 长回答可读.
7. As a 用户, I want 回答长时上翻停跟随、对话区右下角悬浮「↓」小圆钮一键回底、滚到底自动恢复跟随, so that 我看历史时不被拽走、想回最新又很顺.
8. As a 用户, I want 对话区 PgUp/PgDn/Home/End 全支持且点击对话区可聚焦, so that 键盘翻历史不用找鼠标.
9. As a 用户, I want 输入框随换行 1→5 行自动拉高、超过 5 行出内部滚动条, so that 多行输入不挤、不乱.
10. As a 用户, I want Enter 发送、Shift+Enter 换行, so that 长消息可以分段.
11. As a 用户, I want 粘贴图片进输入框时上方出现缩略图条（可点删、点击放大查看）, so that 发图不再是一串路径文本.
12. As a 用户, I want 带图消息以多模态内容发给模型、模型拒图时自动改路径引用重试一次, so that 图片能力缺失时也不报错.
13. As a 用户, I want 模型思考过程以小字淡色块显示在回答上方（默认展开、可折叠）, so that 我知道它「在想什么」又不干扰正文.
14. As a 用户, I want 工具调用默认一行摘要（✓/✗ + 名称 + 参数截断）, so that 长任务不刷屏.
15. As a 用户, I want 点「＋ 详情」展开看完整参数与输出（文件工具出 diff）, so that 出错时能查细节（codex/opencode 对标）.
16. As a 用户, I want 切换会话后再回来，工具调用记录与回答都在（含重启 app 后）, so that 历史对话是完整持久的.
17. As a 用户, I want 会话侧栏显示首条消息摘要；首轮结束后自动生成 AI 短名（仅一次，失败回落摘要），可手动改名, so that 多会话不是一堆 uuid.
18. As a 用户, I want 点「＋ 新会话」随时开新对话，切会话不重建 runtime, so that 多任务并行不丢状态.
19. As a 用户, I want 任务执行中发的新消息自动排队、回合结束按序发出（状态行「已排队 N 条」）, so that 我不会打断正在跑的任务、也不用自己存草稿.
20. As a 用户, I want 执行中点「取消」，当前步骤跑完即停（收尾 banner）而非杀进程, so that 状态干净、可继续.
21. As a 用户, I want 高危工具（执行命令/写文件/删文件）先弹审批卡片（命令预览或 diff + 放行/永久放行/拒绝/编辑参数）, so that 我不会被 agent 越权.
22. As a 用户, I want 编辑参数时原值只读展示、留空保留原值、执行类只出单行框, so that 我改得清楚、不手滑写多行.
23. As a 用户, I want 点「永久放行」按命令前缀写回配置（如 `git *` 以后自动放行）, so that 重复操作不被反复打断.
24. As a 用户, I want 审批卡片任意结果（含放弃）后焦点自动回输入框, so that 我不用再点一下.
25. As a 用户, I want 放弃审批=放弃本轮（工具不执行，文案明示「不是取消任务」）, so that 我不会误以为点错就全没了.
26. As a 用户, I want 开 YOLO 模式整条会话免审批（状态位 [YOLO] 可见、关掉恢复原规则）, so that 我信它的时候不用逐个点.
27. As a 用户, I want Plan 模式先规划不写盘（写/改工具被拦，提示先规划）, so that 大任务先对齐方向.
28. As a 用户, I want 误操作时撤回上一轮（GUI：撤回按钮 + 双击快捷，语义=TUI 双 Esc 等价）, so that 错了能退回.
29. As a 用户, I want 时间旅行（手动快照/回放/分支/回滚）在 GUI 里能用, so that 文件级回退不依赖终端.
30. As a 用户, I want 压缩上下文（/compact 对应 GUI 按钮，提示词可填）, so that 长会话不爆窗.
31. As a 用户, I want 手动注入 skill（/use 对应入口，名称模糊补全）, so that 我想用哪个工作流就调哪个.
32. As a 用户, I want `@` 路径补全与 `/` 命令补全, so that 我不背命令.
33. As a 用户, I want 明暗主题切换且记住上次选择, so that 护眼.
34. As a 用户, I want 配置 MCP server 即插即用（工具名带前缀出现在工具行与详情里）, so that 我扩展能力不重打包.
35. As a 用户, I want 定时任务（schedules/ 目录）启用时 GUI 显示任务列表并可热重载, so that 我不用开着终端管 cron.
36. As a 用户, I want 自检页（/doctor 对应）：端点/凭据/输入通道/可选依赖状态一屏看完, so that 出问题时我能自查.
37. As a 用户, I want 复制对话区任意文本就是 Ctrl+C（选中文本即可，不需要键盘焦点戏法以外的额外步骤）, so that 快捷键符合 Windows 习惯.
38. As a 用户, I want GUI 不劫持 Ctrl+C 退出（退出=关窗；关窗前有未完成任务时确认）, so that 我复制不会被误关程序.
39. As a 用户, I want 同一台机器 TUI 与 GUI 可同时用（共享同一检查点库，写串行、读并行）, so that 我两个形态切换不丢会话.
40. As a 用户, I want 卸载/重装 GUI 后我的 LLM 配置与记忆不丢（配置在 %APPDATA%、记忆在 .jarvis，均与安装目录分离）, so that 升级无感.
41. As a 开发者, I want GUI 逻辑层复用既有 200+ 单测语义（streaming/commands/permissions 零行为改动）, so that 新客户端不引入回归.
42. As a 开发者, I want GUI 崩溃不毁 graph 状态的升级路径（架构 B 独立 runtime 进程的协议预留）, so that 未来多窗口/远程不动协议.
43. As a 小白用户, I want 界面默认收起高级模式（YOLO/Plan/斜杠命令在菜单里）, so that 主界面只有 对话+输入+审批 三块.

## Implementation Decisions

### 框架与打包
- PySide6 仅 QtWidgets（禁 PySide6-Addons/QtWebEngine）；依赖钉 **PySide6-Essentials**（原型实证：pip `PySide6` 元包会连带装 Addons+WebEngine，大包进 exe）。
- Python 解释器 3.14.7 实证兼容（shiboken6 cp310-abi3 wheel 通吃；原清单 3.12 项作废）。
- 打包：Nuitka onedir（单文件不推荐——启动慢）+ Inno Setup 安装包；代码签名（OV/EV）根治杀软误报，发布附 SHA-256 + VirusTotal 自查流程。
- LGPL：Qt DLL 与 exe 同目录动态共存；无 SaaS 分发，义务面小，发布前过一道法务确认。
- 中文 IME = Qt 原生（组合输入事件成熟）；GUI **不**需要 TUI 的 ime_shim/ConPTY 补丁（那是终端协议专属），输入法在 GUI 下开箱可用。

### 架构（进程与事件流）
- 架构 A（本期）：主线程 = Qt 事件循环；每 thread 一个 worker 线程跑 `run_agent_turn`；事件通道 = 既有 5 键 StreamCallbacks（`on_subagent/on_tool_call/on_message_delta/on_message_end/on_status`）→ Qt 信号回主线程；worker 永不直接碰 widget。
- 新增 `src/gui/` 模块（原型形状，全部「照抄 tui 形状换事件泵」的平移）：presenter（TurnPresenter 同构，`call_from_thread` → 信号队列）、hitl（**第三 ask_action**：审批卡片阻塞 worker `threading.Event`，按钮结果经 `decision_from_choice`/`collect_interrupt_decisions` 出同构 dict，resume 契约 `{"decisions":[...]}` 零内核改）、turn_gate（纯 Python 每 thread 门 + FIFO 消息队，门释放经主线程重投递）、main（装配：load_config→mcp→SqliteSaver→permissions→agent→JumpIn→scheduler 门控→Qt 循环）。
- 思考通道（TUI 已知问题①）：共享流层加**可选** `on_thinking` 回调键（5 键不动，缺省零开销；CLI 不传=TUI 现状零变化），模型 reasoning 块在 streaming 消费层识别（langchain 消息 content blocks 中非 text 的 reasoning/thinking 块；具体块形状以实现时深验模型实际流为准）。TUI 侧同 seam 渲染小字淡色（报给 TUI 线）。
- 架构 B（升级路径，本期只留形）：presenter 的 5(+1) 回调序列即线协议；单机 exe 走 in-process bounded channel 语义（codex app-server 先例），未来 `--serve` 多客户端只加 transport 不改协议。

### 会话与历史（TUI 已知问题②③ + 命名）
- 每 thread 独立消息栈（widget 缓存 dict），切会话 = 换栈，不重建 runtime（原型已验手感）。
- 回放：pane 冷建（app 启动/首访旧会话）从检查点消息重建**完整记录**——user/AI 文本 + 工具行（AIMessage.tool_calls × ToolMessage 按 tool_call_id 配对，含输出与错误态）；工具行默认折叠。
- 工具行 = 一行摘要 +「＋ 详情」展开钮（codex 对标文案「＋ 详情」/收起「－ 收起」）：详情区 = 完整 args（JSON）+ 完整输出（等宽，文件类走 diff 渲染复用 `permission_preview` 的 diff 生成）。
- 会话命名：项目级 `sessions.json` 注册表 `{thread_id: {title, ai_generated: bool}}`（gitignore；检查点库不加 schema，注册表可重建）。首轮 `finalize_turn` 后后台一次性生成 AI 短名（当前模型小 prompt；失败/超时静默回落首条用户消息截断 18 字）；侧栏右键/双击改名（写回注册表）。TUI 可共享该注册表（主线自行采纳，非本期范围）。
- `sched-*` 线程侧栏过滤 + 自动清理（沿用 CLI 展示约定）。

### 输入区
- 多行输入框：Enter 提交 / Shift+Enter 换行；1→5 行随内容拉高、>5 行原生内部滚动条（TUI `#input` 约定平移）；提交语义复用 `commands.build_submission` 纯函数（`/` 多行门禁等）。
- 快捷键基线：Ctrl+C/V/X/A 全部原生保留（选中文本即复制；**GUI 不绑任何退出快捷键**，退出=关窗，关窗时有在途任务→确认框）；TUI 的双 Ctrl+C 退出、y 复制会话 id 等终端约定**不**进 GUI。
- 图片附件条：Ctrl+V（剪贴板图）/粘贴图片路径文本 → 复用 `src/clipboard_image`（`try_copy_clipboard_image`/`looks_like_image_path` → temp 落盘）→ 输入框上方缩略图条（≈56×56 圆角 chip + ✕ 移除；点缩略图 → 无边框放大窗，等比 ≤80% 屏，Esc/点击关闭）；提交 → `build_multimodal_content`（OpenAI 多模态 parts）作 `user_input` + `image_fallback_text`（路径引用）作 `user_input_fallback`，`run_agent_turn` 既有 `model_image_input="auto"` 拒图回落语义不变。用户消息气泡内同样带缩略图（可点放大）。
- 审批卡片任一结果 → 焦点回输入框。

### HITL 审批（codex 内联卡片定案）
- 卡片 = 聊天流内联（非模态框，T-006 用户裁定）：工具名 + 参数预览（`permission_preview`：execute 命令预览 / write 全量 diff / edit unified diff / delete 极简卡）+ 四按钮（放行[主按钮默认焦点]/永久放行[前缀可编辑]/拒绝/编辑参数）+「放弃本轮」显式标注（放弃≠取消任务，T-004 风险⑥文案定案）。
- 编辑参数 = 卡片内展开表单（原值只读展示行 + 编辑框；execute 单行、write/edit 多行；留空保留原值——tui-ux10「看得见改」平移）；决策经 `collect_interrupt_decisions` 出 `{"decisions":[...]}`（tui-ux11 全工具 approve/reject/edit 三决策兼容）。
- 永久放行 = `approve_prefix` 命令前缀规则写回 jarvis.json（字符串规则升格对象规则语义不变）；YOLO 线程级免审批同 state 引用 live 生效（GUI 状态位 `[YOLO]` + 徽章）。
- 多中断并发 = FIFO 一次显一卡（codex InterruptManager ≈ tui-ux7 门语义）。

### 排队与取消（tui-ux7/14 语义平移）
- 每 thread 回合门 + 消息 FIFO：执行中发新消息 → 立即入队列（状态行「已排队 N 条」），门释放（回合结束/取消收尾）按序重投；跨 thread 回合可并行（各自门）。
- 取消 = 当前 superstep 跑完即停（RunControl drain 既有语义）+ banner「已取消，正在收尾」。

### LLM 自配（T-003）
- `%APPDATA%\Jarvis\config.json`（安装目录分离；多用户机天然隔离；沿用 `JARVIS_HOME` 覆盖语义；损坏自愈 = 最近 backup 回退，version 字段单调迁移器）。
- 密钥 = Python `keyring` → Windows Credential Manager（纯 ctypes 零原生依赖；用户级条目）；config 只存 `key_ref`；域账号组策略禁 CM 写入 → 降级 DPAPI user-scope（crypt32.CryptProtectData，同不落明文）；key_ref 悬空 → 启动校验，缺失回向导第 3 步不崩。
- 端点探测（Jan 五档）：保存 provider 时 `GET {base}/models`（8s）：OK→填模型下拉 / 401 密钥无效 / 403 无权限 / 429 限流 / 网络错（connection refused 专条）/ 404 提示 /v1；`probe_supported:false` 允许手填 model id（Jan 原语义）。
- 首启 5 步向导可跳过（LM Studio「先跑起来后配远端」）；本地推理端点 `sk-no-key` 占位。
- 项目级 jarvis.json `model` 段 `{provider}` 钉住该项目用哪个 LLM 源；旧 `*_env` 键保留一个版本兼容读。

### 可选依赖与降级（遗留 c）
- 基础 exe 不捆 chromadb/onnxruntime；RAG 缺失自动回落 grep/wiki（AGENTS「Ollama 不可用自动回落」语义），自检页提示可装 wheel 或外部 Ollama。
- 定时任务 = 可选：GUI 配置未启用时不启动 scheduler；启用时同 app 单 scheduler（后启动者检测 runtime 已存在不双开，遗留 d）。
- MCP 即插即拔（jarvis.json `mcps.servers`），连接失败跳过 + 警告不崩（既有语义）。

### 记忆目录（用户全局化）
- 长期信息记忆（偏好/复盘 `agent-memory.md`）默认落 `%USER%\.jarvis`（`JARVIS_HOME` 可改），跨项目复用；项目 `memory/` 仅项目信息记忆；`/memories/` 路由与 `memory=` 注入清单、`/dream` 全局路径措辞随主线版本对齐——**主线正在实现该迁移，GUI 侧不重复实现**：本 spec 的 GUI 工单在主线合并后 rebase `feat/gui-desktop` 到新 main 再实现相关项（依赖边见 tickets）。

### 与 TUI 的边界
- TUI 六文件（tui.py/tui_turn/tui_log/tui_punct/ime_shim/input_probe）保持原样，行为零改动（T-005 裁定）；GUI 与 TUI 共享的公共 seam 仅限：streaming 5(+1) 键回调、commands 纯函数、permissions state、clipboard_image 管线、sessions.json 注册表（TUI 是否读该注册表 = 主线自行采纳，不在本 spec 范围）。

## Testing Decisions

- **GUI 层**：pytest-qt `offscreen`（`QT_QPA_PLATFORM=offscreen`）；纪律：禁用 `tmp_path`（本机 pytest-of-uida0712 WinError 5 中毒），自建目录（`os.makedirs`）；解释器 `D:\python_env\python.exe`；shell = PowerShell。
- **好的测试 = 只测外部行为**：信号/回调契约（worker → 主线程事件形状）、`ask_action` 返回 dict 与 TUI/CLI 同构断言（`decision_from_choice` 边界）、turn_gate FIFO 顺序与门释放语义、sessions.json 读写与命名回落、图片管线纯函数（已有 clipboard_image 测试先例）、五档探测纯函数（status_code→文案表）。
- **复用既有 200+ 单测**：streaming/commands/permissions/resilience 逻辑层零行为改动 → 原样全绿即回归网；新增 `on_thinking` 键 = 可选缺省（CLI/TUI 不传路径断言不变）。
- **先例**：tests/test_tui*.py 的 Textual pilot 打法 → GUI 侧改 PySide6 `QApplication.processEvents` 循环 + widget 断言（原型 smoke 已实证该模式：offscreen 跑真 graph + HITL 卡片循环 + 落盘断言）。
- **打包验收**（后期工单）：干净机/本装 安装→首启向导→配网关→对话 手工验收清单 + 签名/SHA-256/VT 自查流程（自动化到 CI 缓存 C 扩展产物）。

## Out of Scope

- 服务器 + 浏览器形态、web 前端（部署形态裁定 = 单机 exe）。
- 架构 B 独立 runtime worker 进程 / `--serve` 多客户端 / LangSmith 云（P2，本期只留协议形状）。
- C#/Rust 宿主 + Python 边界（T-001 P2）。
- 跨机备份/同步（Continue 式 AES 密文演进档，P2）。
- RAG/Ollama 捆绑进基础 exe（遗留 c：不捆，可选手引）。
- macOS/Linux 适配（Windows 优先；Qt 跨平台能力保留但不测）。
- TUI 侧三已知问题本身的修复（用户报 TUI 线；GUI 按本 spec 对标实现，共享 seam 处 TUI 是否跟改 = 主线决策）。
- 多语言/i18n（中文优先）。

## Further Notes

- 原型（`.scratch/prototype/gui_skeleton.py`，throwaway）已验证：每 thread 消息栈+切会话不重建、HITL 卡片阻塞/恢复真契约、流式 MD 合批 vs 逐 token、粘底/回底、FIFO 排队、图片提交形状；过稿结论与形态定案见 `PROTOTYPE.md`。
- 原型遗留实证项（本 spec 已定案，实现工单验证）：Nuitka+签名+VT（打包工单）、Credential Manager 组策略机器实测（LLM 自配工单：DPAPI 降级路径）、IME 自绘补全弹层组合窗定位（补全工单实现时验）。
- 红线延续：① 实现前 GitHub 先例检索（opencode/codex/Jan/ChatBox/LM Studio/Continue，报告已核）；② deepagents 更新快，动工前经 docs-langchain 确认最新版 stream_events v3 / HITL interrupt-resume / middleware 契约（原型已在 langchain 1.3.18 实证：`invoke` 内部走 v2 事件桥，自定义模型 `_stream` 必须 yield `ChatGenerationChunk`）。
- 工单拆分见 `.scratch/gui-desktop/issues/`（to-tickets 产物）。
