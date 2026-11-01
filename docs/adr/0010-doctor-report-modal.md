# ADR-0010: /doctor 长诊断报告 Modal 化（tui-ux21）

**状态:** 已接受（2026-11-01）

## 背景

用户报障：TUI 输入 `/doctor` 后，诊断报告（几十至上百行）整份写进 `#messages`（CopyableRichLog，贴底聊天日志），出现三个症状：

1. 贴底逻辑自动滚到最新行 → 报告上半截被顶出视区，「看不见剩余的信息」；
2. 右侧 1 格宽滚动条在 ConPTY/Windows 终端下近不可见，滚轮事件透传不稳 → 实际可用的回滚路径不存在；
3. 新消息一来（报告沉入 scrollback），用户感知报告「消失」。

根因：诊断报告是**大块参照型内容**，却被写进为**流式聊天**设计的贴底日志通道——通道语义错配。

## 决策

1. **报告进独立可滚动 `ReportModal`（ModalScreen）**：布局遵循 tui-ux5⑤ Modal 布局规约（内容容器 `width:80%; height:auto; max-height:70%` + body 可滚动 + 按钮行贴模态底）；正文 `Static(markup=False)` 纯文本渲染（报告含 skill 名/路径等不可信文本，禁用 markup 解析）。
2. **键盘滚动**：PgUp/PgDn 绑定（`show=False`，不污染 footer 帮助行）调 `VerticalScroll.scroll_page_up/down()`；Esc 关闭。`AUTO_FOCUS: ClassVar[str] = "#btn_report_close"`——打开即聚焦关闭按钮，单次 Enter/Esc 即关（tui-ux8 审批 modal 默认焦点同族）；关闭后 `after_close` 回焦 `#input`。
3. **TUI `/doctor` 分支**（`_handle_user_message`，`/compact|/dream` 特判之后、通用 `cmd = parts[0]` 之前）：日志区只写一行「正在执行 /doctor…」，然后 `_run_doctor_worker`（线程）复用 `commands.dispatch_command` 内核（CLI 侧零改动），完成经 `call_from_thread` 推 `_apply_doctor_report`（UI 线程）→ `push_screen(ReportModal(result), after_close)`；worker 异常回落纯文本 `命令失败: {exc}`，不炸穿。
4. **不进回合门、不起 spinner**：/doctor 是只读诊断（无模型调用、不写 graph、不触文件写审批），排队进 `_turn_gate_threads` 会无谓阻塞用户下一条消息。
5. **CLI 路径不变**：`--cli` 下 /doctor 仍走通用 dispatch 把报告打到 stdout（终端全宽、无贴底日志概念，无此问题）。

## 被否决的选项

- **报告截断 + 提示总行数**：丢诊断信息，违背 /doctor 用途。
- **写临时文件 + 日志区只给路径**：用户多一步读文件动作，且 TUI 会话内无文件阅读器，路径在 TTY 场景价值低。
- **让 `#messages` 整体可自由滚动（关贴底）**：贴底语义是流式聊天体验的地基（tui-ux16/17 的 Back to bottom、焦点回底皆依赖），为一条参照型输出破坏整条通道不值。
- **deepagents / langchain 上游方案**：不适用——纯 TUI 呈现层问题，与 agent harness 无关。

## 影响

- `src/tui.py`：新增 `ReportModal`（BINDINGS/AUTO_FOCUS/CSS/compose/关闭/翻页动作）；`_handle_user_message` 增 `/doctor` 特判；新增 `_run_doctor_worker` / `_apply_doctor_report`。
- 测试：`tests/test_tui_modals.py` +4（#report_box 可滚动 / 12 行短屏按钮行可见 / 默认焦点关闭按钮 / 不可信文本纯文本渲染）、`tests/test_tui.py` +1（/doctor 流程：报告进模态不写 #messages、Esc 关闭焦点回输入框、单次 Enter 关模态）；目标套件无新增失败。
- 先例：Textual 官方 ModalScreen 居中容器 + 可滚动 body + 固定按钮行范式；opencode 独立可滚动 status 视图；charmbracelet/bubbletea issue #1478（终端 TUI 长输出不可滚动通病）；本仓 tui-ux8（modal 默认焦点、单次 Enter 闭环）。
