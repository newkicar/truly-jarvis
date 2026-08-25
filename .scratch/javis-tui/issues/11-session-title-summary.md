# 11 — 左侧历史对话标题栏显示第一个问题的摘要

**What to build:** TUI 左侧会话侧边栏不再只显示原始 thread_id，改为显示该对话第一条用户消息的摘要（截断 20 字），让用户一眼看出每个对话在聊什么。

**Type:** task

**Status:** todo

**Blocked by:** 无

## 背景

- 当前侧边栏每个会话显示为 `▸ session-a1b2c3d4`（thread_id 原始字符串），用户必须逐个点进去才知道内容。
- `commands.py` 已有 `last_human_text(values)` 可从 checkpoint 的 messages 里提取用户消息文本（截断 50 字），当前只用于 `/history` 展示。
- 侧边栏宽度有限（22 字符，最大 28），需要精简摘要。

## 目标

### 1. 侧边栏显示格式

改动前：
```
▸ session-a1b2c3d4
  session-b2c3d4e5
  session-c3d4e5f6
```

改动后：
```
▸ 帮我写个 fizzbuzz 测试    ← 第一条用户消息摘要
  优化 config.py 性能        ← 第一条用户消息摘要
  session-d4e5f6g7           ← 无用户消息时 fallback 到 thread_id
```

### 2. 摘要提取逻辑

- 取该 thread 的**第一条**人类消息（`messages[0]` 中 type=="human" 的第一条）
- 截断：20 个字符（侧边栏宽度 22，留 2 字符给 `▸ ` 前缀）
- 去掉换行符（`\n` → 空格）
- 若无用户消息或提取失败，fallback 到 thread_id

### 3. 实现方案

**新增函数** `first_human_text(agent, thread_id) -> str`（`commands.py`）：
- 用 `agent.get_state(configurable={"thread_id": thread_id})` 获取 checkpoint values
- 遍历 `values["messages"]`，取第一条 `type=="human"` 的 content
- 截断 20 字返回

**修改** `SessionSidebar.refresh_sessions`（`tui.py`）：
- 对每个 thread_id 调用 `first_human_text(agent, thread_id)` 获取摘要
- label = `f"▸ {摘要}" if thread_id == current else 摘要`

### 4. 性能考虑

- 侧边栏刷新时对每个 thread 都要读 checkpoint，O(N) 次 `get_state` 调用
- 会话数通常 <50，可接受
- 若后续性能问题，可缓存摘要或批量查询

## 非目标

- 不实现实时标题更新（对话过程中标题不变）
- 不实现 AI 自动生成摘要（太重，用首条消息足够）
- 不改变侧边栏折叠/展开逻辑

## 验收

- [ ] 侧边栏每个会话显示第一条用户消息摘要（20 字截断）
- [ ] 无用户消息时 fallback 到 thread_id
- [ ] 当前会话有 `▸ ` 前缀
- [ ] 侧边栏宽度不变（22 字符），摘要不溢出
- [ ] `/sessions` 命令也显示摘要（可选，优先级低）
- [ ] 单测覆盖 `first_human_text` 逻辑
- [ ] TUI 手动冒烟：创建多个对话 → 侧边栏显示不同摘要

## 参考

- 代码：`src/tui.py`（SessionSidebar.refresh_sessions）、`src/commands.py`（last_human_text、session_thread_ids）
- deepagents：`agent.get_state(configurable={"thread_id": ...})` 获取 checkpoint

## Comments

- 2026-08-25：用户要求创建此票，侧边栏显示对话摘要而非原始 ID。
