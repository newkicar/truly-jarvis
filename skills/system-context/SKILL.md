---
name: system-context
description: Use when the user asks "现在几点", "今天几号", "今天星期几", "什么日期", "当前时间", "我在哪", "什么城市", "所在地", "这里的天气", or needs local date/time/location before answering. Do NOT use for research, vault writes, Reports, Inbox, or delegating to researcher. Do NOT read user-profile.md for location.
---

# 系统上下文

## Gotchas（必读）

- **时间不能猜**：必须调 `get_system_context` 或 `scripts/read_context.py`，禁止凭训练记忆回答。
- **位置来自 IP，不是 profile**：城市由 `get_system_context` 内 IP 地理定位推算（ISP 级，非 GPS 精确定位）。**禁止**读 `/memories/user-profile.md` 找所在地。
- **路径是虚拟的**：只用 `/workspace/`、`/vault/`、`/memories/`；CompositeBackend 不认 `E:/...`。
- **IP 定位可能偏差**：VPN/代理会导致城市不准；失败时如实说明，可请用户补充。
- **答完即停**：用户只问时间/位置/本地天气时，用本 skill 拿上下文后作答；查天气可再 `quick_search`，禁止扩成 Reports。

## 完成标准

| 用户问了 | 成功条件 |
|---|---|
| 日期/时间/星期 | `get_system_context` 返回 date/time/weekday |
| 所在城市/位置 | 同一工具返回 city/location（IP 推算）；不可用则说明 |
| 本地天气 | 先拿 city，再 quick_search「{city} 明天天气」 |

## 执行（How）

- **时间 + 城市** → 工具 `get_system_context`（首选）；不可用再 `execute` `scripts/read_context.py`
- **禁止** → `read_file` user-profile、委派 researcher 跑本地脚本
- **回答** → 简短中文，不追加无关任务

## 参考

- 工具 `get_system_context` — 日期时间与 IP 城市
- `scripts/read_context.py` — 备用脚本
