# JARVIS Harness 增强（借鉴 OpenAI Codex）

**日期：** 2026-08-22  
**状态：** ready-for-agent  
**动机：** [openai/codex](https://github.com/openai/codex) 开源了终端 agent harness（Rust `codex-rs/`）。JARVIS 一期–泛化已交付；下一波应补 **会话卫生、配置可追溯、审批扩展**，而非照搬沙箱全家桶。

**参考（只学接口形状，不重写 Rust）：**

| Codex 模块 | 借鉴点 |
|------------|--------|
| [`tools/orchestrator.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/orchestrator.rs) | 工具统一流水线；已审批 call 升级重试不重复弹窗 |
| [`pending_interactive_replay.rs`](https://github.com/openai/codex/blob/main/codex-rs/tui/src/app/pending_interactive_replay.rs) | 线程 replay 只恢复仍 pending 的交互 |
| [`config_layer_source.rs`](https://github.com/openai/codex/blob/main/codex-rs/config/src/config_layer_source.rs) | 多层配置 + 来源 precedence |
| [`hook_runtime.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/hook_runtime.rs) | PermissionRequest hook 先于 Modal |
| [`session/session.rs`](https://github.com/openai/codex/blob/main/codex-rs/core/src/session/session.rs) | 单会话单任务、失败/取消时状态 finalize |

---

## 问题 → 主线

| # | 现象 | 根因 | 方向 |
|---|------|------|------|
| **A** | API 400 后会话「永远坏」 | checkpoint 留 `__pregel_tasks`；TUI/CLI 无诊断入口 | **turn finalize + repair**（02，已部分实现 `repair_stuck_thread`） |
| **B** | 用户搞不清 permission 从哪来 | `.env` / `~/.javis` / `javis.json` 合并无展示 | **`/doctor` + config layer 摘要**（01） |
| **C** | 审批只能改 JSON 或点 Modal | 无 hook 扩展点 | **permission hooks**（03） |

**主线：** 先可观测（01）→ 再可靠（02）→ 再可扩展（03）。不引入 Landlock/Windows sandbox/Guardian LLM。

---

## 非目标

- Rust 重写或引入 Codex 二进制依赖  
- 完整沙箱栈、网络 proxy、企业 MDM requirements.toml  
- 替换 deepagents / LangGraph；仅在现有 `commands` / `streaming` / `permissions` 层加深  

---

## 分期

| 票 | 交付 | 依赖 |
|----|------|------|
| **01** | `/doctor`（CLI+TUI）；`format_config_layers()` 展示 effective 配置来源 | — |
| **02** | turn 失败/取消时 checkpoint finalize；TUI pending HITL 过滤；与 `repair_stuck_thread` 统一 | 01 可选 |
| **03** | `javis.json` `hooks.permission` 或 `hooks/` 目录；审批前 hook 可 allow/deny/ask | 01 |

---

## 验收（phase 整体）

- [ ] 246+ 单测绿；新增票各有单测  
- [ ] README「调试与排错」链到 `/doctor`  
- [ ] 手动：损坏 `default` checkpoint → `/doctor` 提示 + 自动 repair 或明确修复步骤  
- [ ] 手动：hook 脚本对 `git push` deny 生效，且不破坏现有 HITL Modal  

## Comments

- 2026-08-22：自 Codex 开源讨论起草；`repair_stuck_thread`（`c682d3a`）作为 02 的子集已落地，02 票应合并而非重复实现。
