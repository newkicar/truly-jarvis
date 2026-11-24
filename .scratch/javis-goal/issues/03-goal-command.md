# 03 — /goal 命令端到端（三前端）

**What to build:** `/goal <objective>|status|pause|resume|clear` 命令 dispatch（CLI+TUI+GUI 共用，yolo_command_text 式四态幂等文案）；slash 补全条目；goals.json 跨重启持久。

**Blocked by:** 02

**Status:** done

## 背景

- goal 的人类命令面；文案纪律对标 yolo on/off 四态幂等先例。

## 范围

- [ ] `commands.py` 单 dispatch 函数：五子命令 × 四态幂等文案（含终态下 pause/resume 报错、active 下 clear 等）
- [ ] `goal_text` 状态行：objective + 状态 + turns N/M
- [ ] `slash_completion.py` 条目（/goal + 子命令提示）
- [ ] TUI 输入行 / CLI headless / GUI 命令均可用
- [ ] 跨重启持久：启动按 thread_id 载 goals.json；/sessions 切换显示 goal 状态
- [ ] test_commands：五子命令 × 四态文案断言

## 非目标

- 不做自动续跑（票 05）、不做模型工具（票 04）
