# 01 — `/doctor` 与会话/配置层摘要

**What to build:** 新增 `/doctor` 命令（CLI + TUI 共用 `commands.py`），输出会话与配置健康摘要，帮助用户自助排错（API 400、permission 来源、checkpoint 卡住）。

**Type:** task

**Status:** ready-for-agent

**Blocked by:** —

## 背景

- Codex TUI 有 effective config layer 展示（`debug_config.rs` + `ConfigLayerStack`）。  
- JARVIS 配置来自：安装目录 `.env` 回退、`~/.javis`、`{project_root}/javis.json`、环境变量覆盖，用户看不清合并结果。  
- 实测 `default` checkpoint 损坏导致持续 400；用户需要一眼看到「会话是否 stuck」。

## 范围

- [ ] `format_doctor_report(config, agent, thread_id) -> str` 纯函数，含：
  - `project_root`、`MODEL_ID`（masked api key）、MCP 数量、checkpoint db 路径  
  - **config layers**：列出各层来源（install .env / JARVIS_HOME / project javis.json / env override）及关键字段（permissions 摘要、theme）  
  - **session health**：`checkpoint_config_stuck()` 结果；若 stuck 提示 `/delete-session` 或 `-n`  
  - 可选：thread 消息数、最大 checkpoint blob 大小（sqlite 查询）  
- [ ] `/doctor` 注册到 `dispatch_command` + TUI `/` 建议  
- [ ] 单测：fake agent/checkpointer；stuck vs healthy 两种输出  

## 非目标

- 不写回配置；不做 GUI 设置页  
- 不对标 Codex MDM/Enterprise layer  

## 验收

- CLI：`/doctor` 打印可读摘要；stuck 会话明确提示修复步骤  
- TUI：同命令在 RichLog 展示  
- pytest 覆盖 `format_doctor_report` 与 dispatch  
- README「调试与排错」增加 `/doctor` 一行  

## 参考

- Codex: `codex-rs/tui/src/debug_config.rs`  
- JARVIS: `src/config.py`、`src/project_paths.py`、`src/commands.py`（`checkpoint_config_stuck`）
