# 09 — 执行任务时动态转圈动画（对标 OpenCode）

**What to build:** 代理在执行任务（streaming / tool call / 子代理运行）时，输入框下方或 Header 区域显示一个动态旋转的 spinner 动画，让用户知道「正在工作中」而不是卡住了。

**Type:** task

**Status:** todo

**Blocked by:** 无

## 背景

- OpenCode 在代理执行时有两种 spinner：输入框下方的 Knight Rider 扫描条（`"■"/"⬝"`，40ms 间隔）和推理头部的 braille 点阵（`⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`，80ms 间隔）。
- 当前 JARVIS TUI 在代理工作时没有任何视觉反馈——用户看到的是空白等待区，不知道是在思考还是卡死了。
- 特别是长任务（多步 tool call），用户需要一个「还在跑」的信号。

## 目标

### 1. 两种 Spinner 场景

| 场景 | 位置 | 动画风格 | 触发条件 | 停止条件 |
|------|------|----------|----------|----------|
| **思考中** | 输入框下方（当前空白区） | braille 点阵 `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` | `status != idle`（agent 正在处理） | `status == idle` |
| **工具执行中** | 工具行（已有 muted `✓/✗`） | 无需 spinner（已有结果反馈） | — | — |

### 2. 思考中 Spinner（主场景）

- **位置**：输入框正下方，占一行高
- **动画**：braille 字符轮播，10 帧，80ms 间隔（~12.5 FPS）
- **文字**：`⠋ 思考中...` / `⠙ 思考中...` / ……（随帧轮播）
- **颜色**：`theme.warning`（暖色，表示活跃状态）
- **停止**：agent 返回第一条 assistant 消息时隐藏
- **降级**：若终端不支持 braille 或用户配置 `animations=false`，显示静态 `⋯`

### 3. 状态检测

- 用 `streaming.py` 的 `is_streaming` 状态（或轮询 `agent.get_state()` 的 `status`）驱动 spinner 显示/隐藏
- TUI 侧：`@work(thread=True)` 启动时显示 spinner，流式结束后隐藏
- 参考 opencode：`status().type !== "idle"` 驱动 `<Show when={...}>`

### 4. 可配置

- `javis.json` 的 `tui.animations` 字段（布尔，默认 true）控制是否启用动画
- `javis.json` 的 `tui.spinner_style` 字段（`"braille"` / `"blocks"` / `"none"`，默认 `"braille"`）控制动画风格

## 非目标

- 不实现 opencode 的 Knight Rider 扫描条（过复杂，braille 够用）
- 不实现子代理独立 spinner（子代理状态暂无实时暴露）
- 不要求与 opencode 像素级一致

## 验收

- [ ] 代理执行时输入框下方显示 braille 旋转动画
- [ ] 代理空闲时 spinner 消失
- [ ] 动画颜色 = `theme.warning`
- [ ] `tui.animations=false` 时显示静态 `⋯`
- [ ] `tui.spinner_style="none"` 时完全隐藏 spinner
- [ ] 长任务（>5s）期间 spinner 持续旋转不卡顿
- [ ] 单测覆盖 spinner 状态切换逻辑
- [ ] TUI 手动冒烟：发消息 → 看到 spinner → 回复出现 → spinner 消失

## 参考

- OpenCode：`packages/tui/src/component/spinner.tsx`（braille SPINNER_FRAMES）、`packages/tui/src/component/prompt/index.tsx`（spinnerDef、status 驱动）、`packages/tui/src/ui/spinner.ts`（Knight Rider 引擎，本票不实现）
- 代码：`src/tui.py`（StreamingPane、Input 区域）、`src/streaming.py`（流式状态）

## Comments

- 2026-08-25：用户要求创建此票，参考 opencode 的 spinner 实现。
