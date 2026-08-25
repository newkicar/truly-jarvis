# 08 — Tab 切换 Plan/Act 模式 + 输入框变色（对标 OpenCode）

**What to build:** 按 Tab 键在 Plan（只读规划）和 Act（执行）两个代理模式之间切换，输入框左边框颜色随当前模式变化，直观区分当前处于哪种模式。

**Type:** task

**Status:** todo

**Blocked by:** 无

## 背景

- OpenCode 用 Tab 切换 build/plan 两个 primary agent，输入框左边框颜色跟随当前 agent 变色（build=secondary 色，plan=accent 色），切换时有 160ms 渐变动画。
- 当前 JARVIS 只有一个主代理，没有 plan/act 模式区分。用户无法让模型「先规划再执行」，容易直接冲进执行导致返工。
- Tab 是最直觉的切换键位（opencode 约定），用户无需记新快捷键。

## 目标

### 1. 双模式定义

| 模式 | 代理 | 权限 | 用途 |
|------|------|------|------|
| **Act**（默认） | 主代理（当前） | 全工具（execute/write/edit/delete） | 执行任务 |
| **Plan** | 主代理 + plan 系统提示注入 | 只读（ls/read_file/glob/grep/wiki + execute 只读命令） | 先拆解任务、列步骤，不动文件 |

Plan 模式下 **禁止** write_file / edit_file / delete / execute 中的写操作（可通过 `javis.json` 的 `permissions` 段配置 deny 规则，或在 agent 层面注入 plan 提示词禁用）。

### 2. Tab 切换机制

- **Tab**：Act → Plan → Act → Plan ……（循环切换 primary agent 列表，当前只有两个）
- **Shift+Tab**：反向循环
- 切换时触发输入框左边框颜色渐变（160ms Hermite 插值，对标 opencode `createFadeIn`）
- Header sub_title 显示当前模式名：`项目名 | Plan` 或 `项目名 | Act`
- 切换 **不重置** 当前对话历史（同一 thread 内切换模式，消息保留）

### 3. 输入框变色

- Act 模式：左边框 = `theme.secondary`（opencode 的 build agent 色）
- Plan 模式：左边框 = `theme.accent`（opencode 的 plan agent 色）
- 渐变动画：首次切换时 alpha 从 0→1，160ms Hermite 插值
- 参考 opencode 实现：`packages/tui/src/component/prompt/index.tsx` 的 `highlight` / `borderHighlight` / `agentMetaAlpha`

### 4. Plan 模式系统提示注入

Plan 模式下在 system prompt 中追加约束（对标 opencode `session/reminders.ts` 的 PLAN_MODE）：

```
当前处于 Plan 模式。你只能做规划和分析：
- 可以：读取文件、搜索代码、列出目录、分析架构
- 不可以：写入/编辑/删除文件、执行会修改状态的命令
- 输出格式：先输出任务分解清单（write_todos），再逐步分析
- 完成规划后提示用户按 Tab 切回 Act 模式执行
```

### 5. AI 回复标注模式

每条 AI 回复头部标注当前模式（对标 opencode 的 `message.mode` 显示）：
- `[Plan]` 前缀，颜色 = plan accent 色
- `[Act]` 前缀，颜色 = act secondary 色

## 非目标

- 不实现动态子代理 fan-out 的 plan/act 分离（那是一期已有的 researcher/knowledge_keeper）
- 不改变 agent 架构（仍是单主代理，只是提示词 + 权限切换）
- 不要求与 OpenCode 像素级一致

## 验收

- [ ] Tab 键可在 Plan/Act 之间循环切换
- [ ] Shift+Tab 反向循环
- [ ] 输入框左边框颜色随模式变化，切换有渐变动画
- [ ] Header sub_title 显示当前模式名
- [ ] Plan 模式下 write_file/edit_file/delete 被拒绝（或提示词约束模型不调用）
- [ ] 同一对话内切换模式，消息历史保留
- [ ] AI 回复头部标注 `[Plan]` / `[Act]` 模式
- [ ] 单测覆盖模式切换逻辑
- [ ] TUI 手动冒烟：Plan 模式读文件 → Tab 切 Act → 写文件

## 参考

- OpenCode：`packages/tui/src/context/local.tsx`（agent.move、agent.color）、`packages/tui/src/component/prompt/index.tsx`（highlight、borderHighlight、agentMetaAlpha）、`packages/opencode/src/session/reminders.ts`（PLAN_MODE）
- 代码：`src/tui.py`（PasteInput 子类、Header、SessionSidebar）、`src/agent.py`（_make_backend、JARVIS_HARNESS_SUFFIX）、`src/commands.py`（session_thread_ids）
- OpenCode agent 定义：`packages/opencode/src/agent/agent.ts`（plan agent 的 permission 配置）

## Comments

- 2026-08-25：用户要求创建此票，参考 opencode 的 Tab 切换 + 输入框变色实现。
