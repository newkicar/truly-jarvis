# 05 — / 命令建议（注册表 + overlay）

**What to build:** 在 `commands.py` 定义 `SLASH_COMMANDS`（name、usage、summary）；新增 `slash_completion.py`（`slash_query`、`filter_commands`）；TUI 在输入 `/` 时显示过滤列表。

**Blocked by:** —

**Status:** done

## 命令列表（与 dispatch 对齐）

| 命令 | 摘要 |
|------|------|
| `/exit` | 退出（TUI 可不在列表，或标注） |
| `/help` | 完整帮助 |
| `/sessions` | 历史会话 |
| `/history` | 当前会话时间线 |
| `/replay <id>` | 从 checkpoint 重跑 |
| `/fork <id>` | 分叉会话 |
| `/snapshot` | git 文件快照 |
| `/snapshots` | 列出快照 |
| `/rollback <id>` | 回退文件 + Inbox |
| `/reload-schedules` | 热重载定时任务 |

## 范围

- [ ] `SlashCommand` dataclass + `SLASH_COMMANDS` tuple  
- [ ] `TUI_HELP` / `CLI_HELP` 可由注册表生成（可选，减少重复）  
- [ ] `slash_query(value, cursor)`：行首 `/` 且无空格截止  
- [ ] `filter_commands(commands, query, limit=20)`  
- [ ] TUI：`CommandCompletionOverlay` 或复用 `SuggestionOverlay`  
- [ ] 单测：`/his` → `/history`，`/` → 全表

## 非目标

- Tab/Enter 行为（票 06）  
- CLI readline 补全（可选 follow-up）

## 验收

- 输入 `/repl` overlay 含 `/replay`  
- dispatch 行为不变
