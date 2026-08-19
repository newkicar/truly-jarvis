---
name: system-context
description: Use when the user asks "现在几点", "今天几号", "今天星期几", "什么日期", "当前时间", "我在哪", "我的地址", "所在地", or needs local date/time before answering. Do NOT use for research, web search, vault writes, Reports, Inbox, or delegating to researcher.
---

# 系统上下文

## Gotchas（必读）

- **时间不能猜**：训练数据里的日期已过期；必须调 `get_system_context` 或 `scripts/read_context.py`，禁止凭记忆回答。
- **路径是虚拟的**：只用 `/workspace/`、`/vault/`、`/memories/`；CompositeBackend 不认 `E:/...`。
- **位置不能写死**：用户可能在任意地点；JARVIS 无 GPS，不在 `javis.json` 或 profile 预置「所在地」。用户问了位置时，说明无法自动定位，请用户当轮说明或自行告知。
- **答完即停**：用户只问时间/位置时，禁止扩成调研、写 Reports、委派 researcher。

## 完成标准

| 用户问了 | 成功条件 |
|---|---|
| 日期/时间/星期 | 返回 `get_system_context` 的 JSON 字段 |
| 所在地（且明确问了） | 说明无法自动定位；若用户当轮已说明则复述，否则请用户告知 |
| 两者都要 | 以上两项齐全，然后停止 |

## 执行（How）

细节见按需加载，不必一次读完：

- **时间** → 工具 `get_system_context`（首选）；不可用再 `execute` `scripts/read_context.py`
- **位置** → 无自动数据源；按完成标准如实作答
- **回答** → 简短中文，不追加无关任务

## 参考

- 工具 `get_system_context` — 当前日期时间
- `scripts/read_context.py` — 备用脚本
