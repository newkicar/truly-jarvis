# ADR-0001: TUI 界面（Textual，对标 opencode）

**状态:** 已接受（2026-08-18）

## 背景

JARVIS 一期到三期的交互形态是纯 CLI（`input()` 循环）。三期引入 HITL 审批后，
审批流（y/n/e/a）打断对话视线；流式输出（子代理/工具/回答）在纯终端里只能逐行打印，
无法区分消息层级。用户要求对标 opencode 的终端界面，提供更优的交互体验。

## 决策

1. **框架用 Textual**（`textual>=0.40.0`），对标 opencode 的 Bubble Tea 终端 UI。
   选型理由：Python 生态、Rich 渲染、`RichLog` 增量写 + `@work(thread=True)` 天然适配
   `stream_events` 的逐字消费、`ModalScreen` 直接支持审批覆盖层。
2. **命令/会话纯逻辑抽到 `src/commands.py`**（CLI + TUI 共用），`main.py` 只做装配与入口
   分支（`--cli` 回退）。避免同一逻辑两份实现的 shotgun 症状。
3. **消息区样式对标 opencode**：用户消息 secondary 粗竖线、AI 回答 primary 粗竖线 +
   末尾 `模型名 (耗时)`、工具调用 muted `✓/✗ 工具名(参数)`、子代理黄色标题嵌套。
4. **HITL 审批 = `PermissionModal`**（ModalScreen），四按钮：`放行(a)` / `永久放行(s)` /
   `拒绝(d)` / `编辑参数(e)`。比 opencode 的 Allow/Allow for session/Deny 多一个
   「编辑参数」，复用三期已实现的 `edited_action` resume 能力。
   resume 结构 `{"decisions": [...]}` 与 CLI `_handle_interrupts` 完全一致。

## 被否决的选项

- **纯 CLI 维持现状**：审批打断对话，流式层级不清。
- **自定义 ANSI 渲染（不用 Textual）**：重复造轮子，且难做鼠标/键盘/Modal。

## 关键实现点

- 流式：`@work(thread=True)` 后台线程消费 `stream_events(v3)`，`call_from_thread` 逐字
  写 RichLog；`Esc` 通过 `get_current_worker().is_cancelled` 取消。
- 审批衔接：worker 检测 `stream.interrupts` → `call_from_thread` 推 `PermissionModal` +
  `asyncio.Event` 等 dismiss → 收集决策 → `Command(resume=...)` 继续。

## 影响

- `main.py` 默认进 TUI；`--cli` 保留全部原交互（命令 + y/n/e/a 审批），零回归。
- 新增 `src/tui.py`、`src/commands.py`；`tests/test_tui.py`（骨架 + 流式 + Modal）。
- 依赖新增 `textual>=0.40.0`。