# 05 — 主入口 --tui/--cli 分支

**What to build:** `python -m src.main` 默认启动 TUI；`--cli` 参数回退到现有 `input()` 交互。CLI 原有功能（命令、审批 y/n/e/a、流式打印）零回归。

**Blocked by:** 03（流式输出 + 消息样式）、04（权限审批 Modal）

**Status:** done

- [ ] `main()` 增加 `--tui`（默认）/ `--cli` 参数解析；TUI 分支调用 `JarvisApp(config, agent, permission_state, sched).run()`
- [ ] TUI 分支复用现有装配流程：`load_mcp_tools` → `SqliteSaver` → `build_agent` → `build_permission_interrupts` → `make_scheduler`；会话 id 解析（`-n`/`session-*`）与 CLI 一致
- [ ] TUI 分支持有 `SqliteSaver` 上下文（`with` 块），app 退出后正确关闭；调度器正常 shutdown
- [ ] `--cli` 分支行为与现在完全一致（命令、审批、流式打印）
- [ ] 手动冒烟：`python -m src.main` 进 TUI、`python -m src.main --cli` 进旧交互、退出均无资源泄漏警告