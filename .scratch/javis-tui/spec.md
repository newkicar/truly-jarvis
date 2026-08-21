# Spec: JARVIS TUI（对标 opencode 的终端界面）

`Status: done`

> 依赖：一期/二期/三期主体已完成（94 单测全绿）。本 spec 基于用户对现有 CLI 交互的体验反馈与「对标 opencode」的明确意向，在 grill-with-docs 阶段收敛出设计。参见 `.scratch/javis-implementation/map.md`。

## Problem Statement

JARVIS 目前是纯 `input()`/`print()` 的 CLI 交互（`src/main.py`）。用户体验与业界标杆 opencode 的 TUI 差距明显：

- **对话历史不可滚动回看**：工具调用、子代理状态、AI 回答全部平铺打印，终端翻页后无法回溯。
- **消息无视觉区分**：用户消息、AI 回答、工具调用、子代理状态混杂，靠文字前缀区分，长对话难以扫读。
- **HITL 审批交互原始**：每次审批都是裸 `input()` 提示「[y]本次放行 [n]拒绝 [e]编辑参数 [a]always approve」，无上下文预览（要执行的命令长什么样）、无按钮式选择。
- **无状态栏**：当前会话 id、已加载 MCP 工具数、定时任务状态都不可见。

用户明确表示「我对 opencode 的 TUI 页面设计挺满意」，希望 JARVIS 的终端界面在布局、消息样式、权限审批交互上对标 opencode。

## Solution

引入 **Textual** 构建 JARVIS 的 TUI，对标 opencode 的 Bubble Tea 界面设计，但用 Python/Textual 生态实现：

- **消息区**（对标 `messagesCmp`）：RichLog 渲染，每条消息左侧粗竖线分隔——用户消息 secondary 色、AI 回答 primary 色、工具调用 muted 色；工具调用显示 `工具名: 参数摘要` + 截断结果预览（≤10 行）；子代理嵌套缩进显示。
- **底部编辑器**（对标 `editorCmp`）：Input 输入框，顶部边框线与消息区分隔；Enter 提交，Esc 取消当前生成，Ctrl+N 新会话。
- **权限审批**（对标 `permissionDialogCmp`）：ModalScreen 覆盖层，展示工具名/路径/命令或 diff 预览，底部按钮式选择：放行(a) / 永久放行(s) / 拒绝(d) / 编辑参数(e)——比 opencode 多出「编辑参数」，对应 JARVIS 现有 `e` 功能。
- **架构分层**：把 `main.py` 里的命令分发 + 会话管理逻辑抽到 `src/commands.py`（纯逻辑），CLI 与 TUI 共用；`main.py` 加 `--tui`（默认）/ `--cli` 分支，保持向后兼容。
- **入口**：`python -m src.main` 默认进 TUI；`--cli` 保留现有 `input()` 交互。

## Backlog（TUI 后续）

- **07 — Rich 渲染 + 真实鼠标选区**（`.scratch/javis-tui/issues/07-rich-text-selection.md`）：对标 OpenCode 拖选复制，保留 Markdown 样式；**最后实现**。当前用序号命令（`/history` → `/replay N`）、`/copy-session`、侧边栏 Y/D 绕开。

## User Stories

1. 作为用户，我希望启动 JARVIS 后进入一个类似 opencode 的 TUI 界面，以便获得现代化终端体验。
2. 作为用户，我希望对话历史在消息区内可滚动回看，以便随时回溯之前的问答、工具调用、子代理过程。
3. 作为用户，我希望用户消息、AI 回答、工具调用、子代理状态有清晰的视觉区分（不同颜色/缩进），以便长对话快速扫读。
4. 作为用户，我希望每条消息左侧有粗竖线边框、用户与 AI 颜色不同，以便视觉上对标 opencode、快速定位说话方。
5. 作为用户，我希望工具调用显示 `工具名: 参数摘要`，结果预览截断到 ≤10 行，以便不刷屏但能确认工具做了什么。
6. 作为用户，我希望子代理（researcher/knowledge_keeper）的调用嵌套缩进显示其内部工具调用，以便理解委派过程。
7. 作为用户，我希望每条 AI 回答末尾显示模型名与耗时，以便了解性能（对标 opencode 的 `mimo-v2.5 (2.3s)`）。
8. 作为用户，我希望底部有输入框、顶部有状态栏（会话 id、MCP 工具数），以便随时掌握上下文。
9. 作为用户，我希望权限审批弹出 Modal 对话框、展示要执行的命令/写入的文件，以便决策前看清内容。
10. 作为用户，我希望审批对话框用按钮（放行/永久放行/拒绝/编辑参数）+ 键盘快捷键选择，以便对标 opencode、操作高效。
11. 作为用户，我希望「编辑参数」点击后弹出参数编辑界面（预填原值），以便修改命令/路径后再放行。
12. 作为用户，我希望 Esc 能取消当前正在生成/执行的轮次，以便随时中断。
13. 作为用户，我希望 Ctrl+N 能新建会话，以便快速开始新对话。
14. 作为用户，我希望 `/sessions` `/history` `/replay` `/fork` `/snapshot` `/rollback` `/reload-schedules` 等命令在 TUI 内可用，以便不丢失现有能力。
15. 作为用户，我希望 TUI 支持 `--cli` 回退到旧交互，以便在无 TUI 支持的环境（CI/SSH 裸终端）仍能使用。
16. 作为用户，我希望 TUI 实现不破坏现有 94 个单测（CLI 命令逻辑测试迁移后仍全绿），以便回归安全。
17. 作为用户，我希望流式输出在 TUI 内实时可见（AI 逐字出现、工具调用即时显示），以便获得 opencode 同款体验。
18. 作为用户，我希望 TUI 的消息区支持 markdown 渲染（AI 回答是结构化 markdown），以便结论可读。

## Implementation Decisions

- **框架**：`textual>=0.40.0`（Python 的 TUI 框架，对标 Go 的 Bubble Tea）。加进 `requirements.txt`。
- **架构分层（核心决策）**：
  - 新建 `src/commands.py`：承载当前 `main.py` 里的命令分发与会话管理纯逻辑——`dispatch_command`、`list_sessions`、`list_history`、`resolve_checkpoint_id`、`boundary_checkpoints`、`replay`、`fork`、`snapshot`、`list_snapshots`、`rollback`、`last_human_text`、`checkpoint_short_id`、`current_permissions`、`project_root`、`render_markdown` 等，签名保持「接收 agent/thread_id → 返回文本」。
  - `src/main.py`：保留 `_stream_turn`、`_handle_interrupts`（CLI 专用，内部用 `input()`），命令分发改为从 `src/commands.py` import；`main()` 加 `--tui`/`--cli` 分支。
  - 新建 `src/tui.py`：`JarvisApp(App)`（Header + ChatView + Input + Footer）、`PermissionModal(ModalScreen)`、`EditParamsModal(ModalScreen)`、TCSS 样式。
- **消息区（ChatView）**：`RichLog`，`wrap=True`。每条消息一个 Rich 对象：
  - 用户：`Panel` + 左侧 thick 边框，secondary 色标题「你」。
  - AI：左侧 thick 边框，primary 色标题「JARVIS」，内容 markdown 渲染，末尾追加 `mimo-v2.5 (耗时)` muted 文本。
  - 工具调用：muted 色 `✓/✗ 工具名(参数摘要)`，结果预览 ≤10 行。
  - 子代理：黄色标题 `[researcher] running`，内部工具嵌套缩进。
- **流式输出**：`@work(thread=True)` 后台线程跑 `stream_events(v3)`；`get_current_worker().is_cancelled()` 支持 Esc 中断；`call_from_thread` 逐步写入 RichLog。
- **权限审批（PermissionModal）**：对标 opencode `permissionDialogCmp`。
  - 顶部：`Tool: <名>` + `Path: <路径>`（execute 显示 Command，write/edit 显示 File）。
  - 中间：内容预览 viewport——execute 显示命令、write/edit 显示 diff/内容、其余显示描述。
  - 底部 4 按钮：`放行 (a)` / `永久放行 (s)` / `拒绝 (d)` / `编辑参数 (e)`，左右键/Tab 切换、Enter 确认、快捷键直达。
  - 「永久放行」写入 `javis.json`（复用现有 `dump_permissions_json` 逻辑）+ 更新 `permission_state`，不重建 agent。
  - 「编辑参数」→ 弹出 `EditParamsModal`：逐 key 显示 Input（预填原值），确认后返回编辑后的 args。
  - 返回 `{"decisions": [...]}` 结构，与 CLI `_handle_interrupts` 的返回契约一致，复用现有 resume 机制。
- **HITL 中断衔接**：TUI 的 worker 消费 `stream_events` 时检测 `stream.interrupts` → 挂起 worker → `push_screen(PermissionModal)` → 用户选择后 `dismiss` 返回决策 → worker 用 `Command(resume=...)` 继续。
- **键位**：`ctrl+c` 退出（BINDINGS）、`ctrl+n` 新会话、`esc` 取消当前轮次、`Tab` 在审批按钮间切换。
- **样式**：TCSS 内联（`JarvisApp.CSS` 类属性）。配色沿用 Textual 默认 dark 主题的 `$primary`/`$secondary`，不自定义调色板。
- **侧边栏**：暂不实现（session 列表用 `/sessions` 命令）。后续可加。
- **补全对话框**：暂不实现（`@` 文件补全）。后续可加。

## Testing Decisions

- **测试哲学**：只测外部行为，不测实现细节。命令/会话管理逻辑返回文本字符串，断言文本内容而非内部状态。
- **接缝**：`src/commands.py` 的纯逻辑函数是核心测试接缝——它们接收 `agent`/`thread_id`/`checkpoint_id`，返回文本。测试用 `FakeAgent`（模拟 `get_state_history` 返回 checkpoint 序列，见现有 `tests/test_main.py`）驱动，不触网、不碰真 checkpoints.sqlite。
- **迁移**：现有 `tests/test_main.py` 的 6 个测试（boundary_checkpoints / list_history / resolve_checkpoint_id / list_sessions / list_snapshots）迁移到 `tests/test_commands.py`，import 目标从 `src.main` 改为 `src.commands`，断言不变。
- **新增**：
  - `tests/test_commands.py`：补 `dispatch_command` 分发测试（/sessions /history /replay /fork /snapshot /rollback /reload-schedules /未知命令）、`current_permissions` 序列化测试。
  - `tests/test_tui.py`：冒烟——`async with app.run_test()` 启动/退出、输入框提交后路由到 worker、审批 Modal 能弹出/关闭。不测真实流式（留给手动 smoke）。
- **手动**：`smoke_test.py` 增补 TUI 冒烟场景（真实模型 + 审批）。

## Out of Scope

- 侧边栏（session 列表 / 命令面板）——后续迭代。
- `@` 补全对话框（文件/文件夹补全）——后续迭代。
- 权限对话框的完整 diff 渲染（对 write/edit 显示全量 diff）——第一版显示内容摘要即可。
- 多主题/自定义配色——用 Textual 默认 dark 主题。
- Web 端渲染（Textual 可导出 web）——本期不做。

## Further Notes

- opencode 参考实现：`internal/tui/page/chat.go`（SplitPane 布局：messages + editor）、`internal/tui/components/dialog/permission.go`（Permission 对话框：Tool/Path 头 + 内容 viewport + 三按钮）、`internal/tui/components/chat/message.go`（消息渲染：粗竖线边框、工具嵌套缩进、模型+耗时）。
- 权限语义差异：opencode 是 Allow / Allow for session / Deny 三按钮；JARVIS 是 放行 / 永久放行 / 拒绝 / 编辑参数 四按钮——「永久放行」对应 opencode 的 allow for session 但持久化到 javis.json；「编辑参数」是 JARVIS 独有的增强（对应现有 CLI 的 `e`）。
- 实施应分阶段（见 ticket），每阶段可独立测试。